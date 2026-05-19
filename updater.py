"""
Copasta self-updater.

Checks GitHub Releases for a newer version. If the user agrees, downloads
Copasta.zip, verifies Copasta.zip.sha256, extracts to a temp folder, and runs a
PowerShell helper that:

  1. Waits for the running Copasta.exe to exit.
  2. Copies Copasta.exe and _internal/ into the install folder.
  3. Relaunches Copasta via a short deferred .cmd script.
  4. Self-deletes.

If the install directory is not writable (e.g. Program Files), the helper is
launched elevated via UAC.

Dev-mode safe: apply_update() refuses when not running the packaged exe.
"""

import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import shutil
import tkinter as tk
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import ttkbootstrap as ttk
except ImportError:
    from tkinter import ttk  # type: ignore


GITHUB_OWNER = "Levati-Wolfson"
GITHUB_REPO = "copasta-app"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
ZIP_ASSET_NAME = "Copasta.zip"
ZIP_SHA256_ASSET_NAME = "Copasta.zip.sha256"
EXE_NAME = "Copasta.exe"

HTTP_TIMEOUT_SECONDS = 28
DOWNLOAD_TIMEOUT_SECONDS = 120
USER_AGENT = "Copasta-Updater (+https://github.com/Levati-Wolfson/copasta-app)"

logger = logging.getLogger(__name__)

# Matches Copasta Tk / bootstrap dark chrome (avoid native Win32 white messageboxes).
_DARK_BG = "#2b2b2b"
_DARK_FG = "#ffffff"
_DARK_FG_DIM = "#cccccc"
_DARK_BTN = "#375a7f"
_DARK_ERR = "#8b3a3a"


def apply_dark_windows_titlebar(widget):
    """Request dark mode + dark caption colors for a Tk hwnd (Windows 10 build 17763+, Win11).

    Tk cannot paint the OS title bar itself; we ask Desktop Window Manager instead.
    No-op elsewhere or if DWMAPI rejects the call."""
    if sys.platform != "win32":
        return
    try:
        widget.update_idletasks()
        hwnd = int(widget.winfo_id())
    except Exception:
        return
    if not hwnd:
        return
    try:
        ddll = ctypes.windll.dwmapi
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35

        rv = ctypes.c_int(1)
        ddll.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(rv),
            ctypes.sizeof(rv),
        )
        # Approximate caption #2b2b2b (COLORREF 0x00 BB GG RR)
        cap = ctypes.c_uint(0x002B2B2B)
        ddll.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_CAPTION_COLOR),
            ctypes.byref(cap),
            ctypes.sizeof(cap),
        )
    except Exception:
        logger.debug("DwmSetWindowAttribute (dark titlebar) unavailable", exc_info=True)

def _center_on_parent_popup(parent, win):
    """Place win near parent's center."""
    win.update_idletasks()
    try:
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px = parent.winfo_rootx() + max(0, (pw - win.winfo_width()) // 2)
        py = parent.winfo_rooty() + max(0, (ph - win.winfo_height()) // 3)
        win.geometry(f"+{max(0, px)}+{max(0, py)}")
    except Exception:
        pass


def _show_dark_message(
    parent,
    title,
    body,
    *,
    is_error=False,
    auto_close_seconds=0,
    on_finished=None,
):
    """Dark Tk dialog replacing native messagebox.

    auto_close_seconds: countdown then exits; invokes on_finished afterward.
    on_finished=None: dialog-only (OK button)."""

    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=_DARK_BG)
    win.resizable(False, False)
    try:
        win.transient(parent)
    except Exception:
        pass

    frm = tk.Frame(win, bg=_DARK_BG, padx=20, pady=18)
    frm.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frm,
        text=title,
        fg=_DARK_FG,
        bg=_DARK_BG,
        font=("Segoe UI", 12, "bold"),
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 8))

    tk.Label(
        frm,
        text=body,
        fg=_DARK_FG,
        bg=_DARK_BG,
        font=("Segoe UI", 10),
        anchor="nw",
        justify=tk.LEFT,
        wraplength=432,
    ).pack(fill=tk.X)

    timer_lbl = None
    state = {"done": False, "timer_ids": []}

    def finalize():
        if state["done"]:
            return
        state["done"] = True
        for tid in state["timer_ids"]:
            try:
                win.after_cancel(tid)
            except Exception:
                pass
        state["timer_ids"].clear()
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        if on_finished is not None:
            try:

                def _run():
                    try:
                        logger.info("Update dialog invoking quit/on_finished callback.")
                        on_finished()
                    except Exception:
                        logger.exception("updater dialog on_finished raised")

                parent.after_idle(_run)
            except Exception:

                try:
                    on_finished()
                except Exception:
                    logger.exception("updater dialog on_finished raised")

    btn_kwargs = dict(
        fg=_DARK_FG,
        activeforeground=_DARK_FG,
        relief=tk.FLAT,
        padx=18,
        pady=7,
        font=("Segoe UI", 10),
        cursor="hand2",
    )

    if is_error:
        pass  # buttons packed in bottom row frame below
    elif auto_close_seconds > 0:
        hint = (
            "When the countdown finishes, Copasta exits so files can update. "
            "If Copasta doesn't reopen within about a minute, start it manually "
            "from this folder."
        )
        tk.Label(
            frm,
            text=hint,
            fg=_DARK_FG_DIM,
            bg=_DARK_BG,
            font=("Segoe UI", 9),
            anchor="w",
            justify=tk.LEFT,
            wraplength=432,
        ).pack(fill=tk.X, pady=(10, 0))

        timer_lbl = tk.Label(
            frm,
            text=f"This window closes in {auto_close_seconds} second(s)…",
            fg=_DARK_FG_DIM,
            bg=_DARK_BG,
            font=("Segoe UI", 9, "italic"),
            anchor="w",
        )
        timer_lbl.pack(fill=tk.X, pady=(6, 0))

        def countdown_remaining(n_left):
            if state["done"]:
                return
            try:
                if not win.winfo_exists():
                    return
            except tk.TclError:
                return
            if timer_lbl and timer_lbl.winfo_exists():
                timer_lbl.config(
                    text=f"This window closes in {n_left} second(s)…"
                )
            if n_left <= 0:
                finalize()
                return
            tid = win.after(
                1000,
                lambda nl=n_left - 1: countdown_remaining(nl),
            )
            state["timer_ids"].append(tid)

        countdown_remaining(auto_close_seconds)

    btn_frm = tk.Frame(frm, bg=_DARK_BG)
    btn_frm.pack(fill=tk.X, pady=(16, 0))

    if is_error:
        tk.Button(
            btn_frm,
            text="OK",
            command=finalize,
            bg=_DARK_ERR,
            activebackground=_DARK_ERR,
            **btn_kwargs,
        ).pack(side=tk.RIGHT)
    elif auto_close_seconds > 0:
        tk.Button(
            btn_frm,
            text="Continue now",
            command=finalize,
            bg=_DARK_BTN,
            activebackground=_DARK_BTN,
            **btn_kwargs,
        ).pack(side=tk.RIGHT)
    else:
        tk.Button(
            btn_frm,
            text="OK",
            command=finalize,
            bg=_DARK_BTN,
            activebackground=_DARK_BTN,
            **btn_kwargs,
        ).pack(side=tk.RIGHT)

    try:
        win.grab_set()
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass

    _center_on_parent_popup(parent, win)

    win.after_idle(lambda: apply_dark_windows_titlebar(win))
    win.after(150, lambda: apply_dark_windows_titlebar(win))


def show_dark_info(parent, title, body, *, is_error=False):
    """Dark modal for Help/about-style text (avoids native white messageboxes)."""
    _show_dark_message(parent, title, body, is_error=is_error)


# ---------------------------------------------------------------------------
# Version parsing


_VERSION_RE = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*$")


def parse_version(s):
    """Parse 'v6.22', '6.22', '6.22.1' into a tuple (6, 22, 0/1).

    Returns None if the string can't be parsed.
    """
    if not isinstance(s, str):
        return None
    m = _VERSION_RE.match(s)
    if not m:
        return None
    return (
        int(m.group(1) or 0),
        int(m.group(2) or 0),
        int(m.group(3) or 0),
    )


def compare_versions(a, b):
    """Return -1, 0, or 1 for tuple/str versions a vs b. Unparseable -> 0."""
    ta = parse_version(a) if isinstance(a, str) else a
    tb = parse_version(b) if isinstance(b, str) else b
    if ta is None or tb is None:
        return 0
    if ta < tb:
        return -1
    if ta > tb:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Update info


class UpdateInfo:
    """Parsed information about a candidate update."""

    __slots__ = ("version", "tag", "download_url", "sha256_url", "notes")

    def __init__(self, version, tag, download_url, sha256_url, notes):
        self.version = version
        self.tag = tag
        self.download_url = download_url
        self.sha256_url = sha256_url
        self.notes = notes

    def __repr__(self):
        return f"UpdateInfo(version={self.version!r}, tag={self.tag!r})"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no `requests` dependency to keep the bundle slim)


def _ssl_context():
    """Default SSL context. Verifies certs. Uses system trust store on Windows."""
    return ssl.create_default_context()


def _url_open_with_retries(req, timeout):
    """Open URL with transient network retries."""
    delays = (0.0, 1.25, 3.0)
    last_err = None
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            return urlopen(req, timeout=timeout, context=_ssl_context())
        except HTTPError as e:
            if e.code in (408, 429, 500, 502, 503, 504) and attempt < len(delays) - 1:
                last_err = e
                continue
            raise
        except (URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < len(delays) - 1:
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("urlopen retry logic fell through")


def _http_get(url, timeout=HTTP_TIMEOUT_SECONDS, accept=None):
    """GET a URL with a User-Agent header. Returns the raw response bytes."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = Request(url, headers=headers)
    with _url_open_with_retries(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_json(url, timeout=HTTP_TIMEOUT_SECONDS):
    raw = _http_get(url, timeout=timeout, accept="application/vnd.github+json")
    return json.loads(raw.decode("utf-8"))


def _http_download(url, dest_path, progress_cb=None, timeout=DOWNLOAD_TIMEOUT_SECONDS):
    """Stream-download url to dest_path. progress_cb(bytes_done, total_or_None)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    req = Request(url, headers=headers)
    tmp_path = dest_path + ".part"
    bytes_done = 0
    total = None
    with _url_open_with_retries(req, timeout=timeout) as resp:
        cl = resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            total = int(cl)
        with open(tmp_path, "wb") as out:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bytes_done += len(chunk)
                if progress_cb is not None:
                    try:
                        progress_cb(bytes_done, total)
                    except Exception:
                        pass
    os.replace(tmp_path, dest_path)
    return dest_path


# ---------------------------------------------------------------------------
# Release-notes rendering (markdown -> plain text)


_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<![*_])[*_]([^*_\n]+)[*_](?![*_])")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_BULLET_RE = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_MD_NUM_RE = re.compile(r"^\s{0,3}\d+\.\s+", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def render_release_notes(body):
    """Convert markdown-ish release body to readable plain text."""
    if not body:
        return ""
    text = body.replace("\r\n", "\n")
    text = _HTML_COMMENT_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _MD_ITALIC_RE.sub(lambda m: m.group(1), text)
    text = _MD_INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = _MD_LINK_RE.sub(lambda m: m.group(1), text)
    text = _MD_BULLET_RE.sub("- ", text)
    text = _MD_NUM_RE.sub("- ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ---------------------------------------------------------------------------
# Release lookup


def _extract_asset_url(release_json, asset_name):
    for asset in release_json.get("assets", []) or []:
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url")
    return None


def fetch_latest_release_ex():
    """Return (UpdateInfo | None, detail_message_if_none).

    detail_message explains why we could not treat GitHub as \"latest\" (not just
    network — could be missing assets, bad tag, etc.).
    """
    try:
        data = _http_get_json(LATEST_RELEASE_API)
    except HTTPError as e:
        msg = "GitHub returned HTTP %s for the releases API." % e.code
        if e.code == 403:
            msg += (
                " This can be rate limiting (try again in a few minutes) or a "
                "network filter blocking api.github.com."
            )
        logger.info("Update check: %s (%s)", msg, e)
        return None, msg
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        msg = (
            "Could not contact GitHub (%s).\n\n"
            "Your browser might still load github.com fine — Copasta talks to "
            "api.github.com, which corporate networks sometimes block separately."
            % (e,)
        )
        logger.info("Update check: releases API unreachable (%s)", e)
        return None, msg
    except Exception as e:
        logger.exception("Update check: unexpected error fetching release")
        return None, "Unexpected error: %s" % e

    tag = data.get("tag_name") or ""
    version_tuple = parse_version(tag)
    if version_tuple is None:
        msg = "Latest release tag %r is not a usable version number." % (tag,)
        logger.warning("Update check: %s", msg)
        return None, msg

    if data.get("draft") or data.get("prerelease"):
        msg = "The latest GitHub release is marked draft or pre-release."
        logger.info("Update check: %s", msg)
        return None, msg

    zip_url = _extract_asset_url(data, ZIP_ASSET_NAME)
    zip_sha = _extract_asset_url(data, ZIP_SHA256_ASSET_NAME)

    if not (zip_url and zip_sha):
        msg = (
            "Release %s has no %s + %s assets."
            % (tag, ZIP_ASSET_NAME, ZIP_SHA256_ASSET_NAME)
        )
        logger.warning("Update check: %s", msg)
        return None, msg

    notes = render_release_notes(data.get("body") or "")
    version_str = "{}.{}.{}".format(*version_tuple)
    info = UpdateInfo(
        version=version_str,
        tag=tag,
        download_url=zip_url,
        sha256_url=zip_sha,
        notes=notes,
    )
    return info, None


def fetch_latest_release():
    """Return UpdateInfo for the latest release, or None on any failure."""
    info, _detail = fetch_latest_release_ex()
    return info


def check_for_update(current_version, skipped_version=None):
    """Return UpdateInfo if a strictly newer non-skipped release exists, else None."""
    info, detail = fetch_latest_release_ex()
    if info is None:
        if detail:
            logger.info("Update check: no candidate release (%s)", detail)
        return None
    if compare_versions(info.version, current_version) <= 0:
        logger.info(
            "Update check: latest %s is not newer than current %s",
            info.version, current_version,
        )
        return None
    if skipped_version and compare_versions(info.version, skipped_version) == 0:
        logger.info("Update check: latest %s was skipped by user", info.version)
        return None
    return info


# ---------------------------------------------------------------------------
# File / filesystem helpers


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


_HEX64_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def _parse_sha256_file_bytes(raw):
    """Pull a 64-char hex digest out of a .sha256 file (supports `sha256sum` format)."""
    text = raw.decode("utf-8", errors="replace")
    m = _HEX64_RE.search(text)
    return m.group(1).lower() if m else None


def _test_dir_writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".copasta_write_test_", dir=path)
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def _find_local_update_zip(install_dir):
    """Dev/test helper: Copasta.zip + Copasta.zip.sha256 beside install or parent folder."""
    install_dir = os.path.abspath(install_dir)
    for base in (install_dir, os.path.dirname(install_dir)):
        zip_path = os.path.join(base, ZIP_ASSET_NAME)
        sha_path = zip_path + ".sha256"
        if os.path.isfile(zip_path) and os.path.isfile(sha_path):
            return zip_path, sha_path
    return None, None


def _extract_update_zip(zip_path, extract_root):
    """Extract Copasta.zip; return the folder with Copasta.exe and _internal."""
    os.makedirs(extract_root, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_root)
    for root, dirs, files in os.walk(extract_root):
        if EXE_NAME in files and "_internal" in dirs:
            return root
    nested = os.path.join(extract_root, "Copasta")
    if os.path.isfile(os.path.join(nested, EXE_NAME)) and os.path.isdir(
        os.path.join(nested, "_internal")
    ):
        return nested
    raise ValueError("Update zip does not contain Copasta.exe and _internal/")


def _machine_staging_dir():
    """Hold Copasta_new.exe and PS helpers outside synced install dirs.

    Prefer per-user TEMP (LOCALAPPDATA\\Temp\\copasta_update): it is outside the
    install folder without cloud-sync path locks, and PowerShell reliably runs
    scripts from profile temp.

    Fallback to WINDIR\\Temp\\copasta_update (or tempfile.gettempdir()) if profile
    temp cannot be written; some policies block executing scripts under WINDIR
    Temp, which is why it is only a fallback.
    """
    local_app = os.environ.get("LOCALAPPDATA") or ""
    gt = tempfile.gettempdir()
    windir = os.environ.get("WINDIR", r"C:\Windows")

    candidates = []
    if local_app:
        candidates.append(os.path.join(local_app, "Temp", "copasta_update"))
    candidates.append(os.path.join(gt, "copasta_update"))
    candidates.append(os.path.join(windir, "Temp", "copasta_update"))

    seen_norm = set()
    for raw in candidates:
        key = os.path.normcase(os.path.normpath(raw))
        if key in seen_norm:
            continue
        seen_norm.add(key)
        try:
            os.makedirs(raw, exist_ok=True)
            if _test_dir_writable(raw):
                wind_fb = os.path.normcase(
                    os.path.normpath(os.path.join(windir, "Temp", "copasta_update"))
                )
                if key == wind_fb:
                    logger.warning(
                        "Updater: WINDIR temp staging fallback %s "
                        "(profile temp not writable or missing)",
                        raw,
                    )
                return raw
        except OSError:
            continue

    d_last = candidates[-1]
    os.makedirs(d_last, exist_ok=True)
    logger.warning(
        "Staging dir write test failed on all preferred paths; using %s", d_last
    )
    return d_last


def cleanup_stale_download_artifacts():
    """Remove Copasta_new.exe beside the exe left by older updater builds."""
    exe = _current_exe_path()
    if not exe:
        return
    stale = os.path.join(os.path.dirname(exe), "Copasta_new.exe")
    try:
        if os.path.isfile(stale):
            os.remove(stale)
            logger.info("Removed stale Copasta_new.exe next to Copasta.exe.")
    except OSError:
        logger.info("Stale Copasta_new.exe could not be removed (open elsewhere?).")


def _current_exe_path():
    """Path to the running Copasta.exe (or None when running from source)."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return None


# ---------------------------------------------------------------------------
# Self-update execution

def _escape_for_ps_single_quotes(text):
    """Escape for embedding in PowerShell single-quoted strings."""
    return str(text).replace("'", "''")


def _is_cloud_synced_install_path(path):
    p = os.path.abspath(path).lower()
    return any(
        token in p
        for token in ("dropbox", "onedrive", "google drive", "icloud")
    )


def _escape_for_cmd_set_value(text):
    """Escape for `set "VAR=value"` in a batch file."""
    return str(text).replace("%", "%%").replace('"', '""')


_HELPER_PS1_TEMPLATE = r"""# Copasta self-updater helper. Auto-generated.
$ErrorActionPreference = 'Continue'
try {{
    [void][System.IO.File]::AppendAllText(
        [System.IO.Path]::Combine($env:TEMP, 'copasta_update_boot.txt'),
        ((Get-Date).ToString('o') + ' copasta_update.ps1 entry (zip)' + [Environment]::NewLine)
    )
}} catch {{ }}
$installDir = '{install_dir}'
$exeName    = '{exe_name}'
$oldExe     = Join-Path $installDir $exeName
$newPkg     = '{new_pkg}'
$parentPid  = {parent_pid}
$logPath    = '{log_path}'
$relaunchPs1 = '{relaunch_script}'
$pendingLeaf = [System.IO.Path]::GetFileNameWithoutExtension($exeName) + '.pending_delete.exe'
$pendingDelete = Join-Path $installDir $pendingLeaf
$diagLog = [System.IO.Path]::Combine([Environment]::GetEnvironmentVariable('SystemRoot'), 'Temp', 'copasta_update_diag.txt')
$diagUser = [System.IO.Path]::Combine($env:TEMP, 'copasta_update_diag_user.txt')

function Log($msg) {{
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $line = "$stamp $msg"
    try {{ Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8 -ErrorAction Stop }} catch {{
        try {{ [System.IO.File]::AppendAllText($logPath, "$line`n") }} catch {{ }}
    }}
    try {{ [System.IO.File]::AppendAllText($diagLog, "$line`n") }} catch {{ }}
    try {{ [System.IO.File]::AppendAllText($diagUser, "$line`n") }} catch {{ }}
}}

function CopastaParentStillRunning {{
    param([int]$WatchPid, [string]$ExePathFull)
    $proc = Get-Process -Id $WatchPid -ErrorAction SilentlyContinue
    if (-not $proc) {{ return $false }}
    try {{
        $exe = [System.Diagnostics.Process]::GetProcessById($WatchPid).MainModule.FileName
        return [string]::Compare([System.IO.Path]::GetFullPath($exe), $ExePathFull, $true) -eq 0
    }} catch {{
        try {{
            $wp = Get-CimInstance Win32_Process -Filter "ProcessId=$WatchPid" -ErrorAction SilentlyContinue
            if (-not $wp) {{ return $false }}
            return [string]::Compare([System.IO.Path]::GetFullPath($wp.ExecutablePath), $ExePathFull, $true) -eq 0
        }} catch {{
            $wantLeaf = [System.IO.Path]::GetFileNameWithoutExtension([System.IO.Path]::GetFileName($ExePathFull))
            return ($proc.ProcessName -ieq $wantLeaf)
        }}
    }}
}}

Log "Helper started (zip/onedir). installDir=$installDir newPkg=$newPkg parentPid=$parentPid"

$oldExeFull = [System.IO.Path]::GetFullPath($oldExe)
$waitProcDeadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $waitProcDeadline) {{
    if (-not (CopastaParentStillRunning $parentPid $oldExeFull)) {{ break }}
    Start-Sleep -Milliseconds 400
}}
if (CopastaParentStillRunning $parentPid $oldExeFull) {{
    Log "Timed out waiting for Copasta (PID $parentPid) to exit."
    exit 1
}}
Start-Sleep -Seconds 14

$swapDeadline = (Get-Date).AddSeconds(120)
$replaced = $false
while ((Get-Date) -lt $swapDeadline) {{
    if (-not (Test-Path -LiteralPath (Join-Path $newPkg $exeName))) {{
        Log "Staged package missing Copasta.exe under $newPkg"
        Start-Sleep -Seconds 2
        continue
    }}
    try {{
        if (Test-Path -LiteralPath $oldExe) {{
            try {{
                Rename-Item -LiteralPath $oldExe -NewName $pendingLeaf -Force -ErrorAction Stop
                Log "Renamed existing exe aside to $pendingLeaf"
            }} catch {{
                Remove-Item -LiteralPath $oldExe -Force -ErrorAction Stop
                Log "Removed existing exe via delete"
            }}
        }}
        Copy-Item -LiteralPath (Join-Path $newPkg $exeName) -Destination $oldExe -Force -ErrorAction Stop
        Log "Copied new Copasta.exe into install dir."
        $srcInternal = Join-Path $newPkg '_internal'
        $dstInternal = Join-Path $installDir '_internal'
        if (Test-Path -LiteralPath $dstInternal) {{
            Remove-Item -LiteralPath $dstInternal -Recurse -Force -ErrorAction Stop
        }}
        Copy-Item -LiteralPath $srcInternal -Destination $dstInternal -Recurse -Force -ErrorAction Stop
        Log "Replaced _internal folder from update package."
    }} catch {{
        Log ("Onedir promote failed: " + $_.Exception.Message)
        Start-Sleep -Milliseconds 600
        continue
    }}
    if (-not (Test-Path -LiteralPath $oldExe)) {{
        Log "ERROR Copasta.exe missing after onedir promote."
        Start-Sleep -Milliseconds 600
        continue
    }}
    if (-not (Test-Path -LiteralPath (Join-Path $installDir '_internal'))) {{
        Log "ERROR _internal missing after onedir promote."
        Start-Sleep -Milliseconds 600
        continue
    }}
    try {{
        if (Test-Path -LiteralPath $pendingDelete) {{
            Remove-Item -LiteralPath $pendingDelete -Force -ErrorAction Stop
        }}
    }} catch {{
        Log ("Leaving pending-delete until next boot: " + $_.Exception.Message)
    }}
    $replaced = $true
    break
}}

if (-not $replaced) {{
    Log "Onedir replace failed after timeout."
    exit 1
}}

Log "Replace succeeded; spawning deferred relaunch cmd."
$sysCmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
try {{
    Start-Process -FilePath $sysCmd -ArgumentList @('/c', 'start', '""', '/min', $relaunchPs1) -WindowStyle Hidden | Out-Null
    Log "Deferred relaunch cmd started."
}} catch {{
    Log ("Deferred relaunch cmd start failed: " + $_.Exception.Message)
}}

$selfPath = $MyInvocation.MyCommand.Path
Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile','-WindowStyle','Hidden','-Command',
    "Start-Sleep -Seconds 2; Remove-Item -LiteralPath `"$selfPath`" -Force -ErrorAction SilentlyContinue"
) -WindowStyle Hidden | Out-Null
"""


def _write_delayed_relaunch_script(staging_dir, install_dir, exe_name):
    """Write a detached .cmd that waits briefly, then launches Copasta (onedir)."""
    install_dir = os.path.abspath(install_dir)
    exe_path = os.path.join(install_dir, exe_name)
    log_path = os.path.join(install_dir, "copasta.log")
    diag_path = os.path.join(
        os.environ.get("TEMP", os.path.expanduser("~")), "copasta_update_diag_user.txt"
    )
    wait_pings = 31 if _is_cloud_synced_install_path(install_dir) else 16
    install_q = _escape_for_cmd_set_value(install_dir)
    exe_q = _escape_for_cmd_set_value(exe_path)
    log_q = _escape_for_cmd_set_value(log_path)
    diag_q = _escape_for_cmd_set_value(diag_path)
    lines = [
        "@echo off",
        "setlocal EnableExtensions",
        f"set \"INSTALLDIR={install_q}\"",
        f"set \"EXE={exe_q}\"",
        f"set \"LOG={log_q}\"",
        f"set \"DIAG={diag_q}\"",
        f'>>"%DIAG%" echo [relaunch] onedir relaunch (~{wait_pings - 1}s wait)',
        f"ping -n {wait_pings} 127.0.0.1 >nul",
        'if exist "%INSTALLDIR%\\Copasta\\_copasta_runtime" rmdir /s /q "%INSTALLDIR%\\Copasta\\_copasta_runtime" 2>nul',
        '>>"%DIAG%" echo [relaunch] launching Copasta',
        'cd /d "%INSTALLDIR%"',
        'start "" "%EXE%"',
        "ping -n 16 127.0.0.1 >nul",
        'findstr /C:"Logging initialized" "%LOG%" >nul 2>&1',
        "if errorlevel 1 (",
        '  >>"%DIAG%" echo [relaunch] WARNING copasta.log not updated yet; user may need to start manually',
        ") else (",
        '  >>"%DIAG%" echo [relaunch] copasta.log shows successful startup',
        ")",
        "del \"%~f0\" 2>nul",
        "endlocal",
    ]
    path = os.path.join(staging_dir, "copasta_delayed_relaunch.cmd")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines))
        f.write("\r\n")
    return path


def _write_helper_script(
    script_staging_dir,
    install_dir,
    exe_name,
    parent_pid,
    relaunch_script_path,
    new_pkg_dir,
):
    """Write a PowerShell script that performs the swap. Returns its path."""
    log_path = os.path.join(install_dir, "copasta_update_helper.log")
    script = _HELPER_PS1_TEMPLATE.format(
        install_dir=_escape_for_ps_single_quotes(os.path.abspath(install_dir)),
        exe_name=_escape_for_ps_single_quotes(exe_name),
        new_pkg=_escape_for_ps_single_quotes(os.path.abspath(new_pkg_dir)),
        parent_pid=int(parent_pid),
        log_path=_escape_for_ps_single_quotes(log_path),
        relaunch_script=_escape_for_ps_single_quotes(
            os.path.abspath(relaunch_script_path)
        ),
    )
    script_path = os.path.join(script_staging_dir, "copasta_update.ps1")
    with open(script_path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(script)
    return script_path


def _launch_helper(script_path, elevated):
    """Launch the PowerShell swap helper.

    Prefer ShellExecuteW(open) without elevation: packaged Copasta often runs in a
    Windows Job Object where CreateProcess BREAKAWAY is ineffective, so subprocess-
    spawned PowerShell dies with the parent before it can swap. ShellExecute usually
    outlives that. Elevated installs still use runas.
    """

    winds = os.environ.get("WINDIR", r"C:\Windows")
    ps_exe = os.path.join(
        winds,
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if not os.path.isfile(ps_exe):
        ps_exe = "powershell.exe"

    script_path = os.path.abspath(script_path)
    cwd = os.path.dirname(script_path)
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    CREATE_BREAKAWAY_FROM_JOB = getattr(
        subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000
    )
    HELPER_CREATION_FLAGS = (
        CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB
    )

    SW_HIDE = 0
    safe_path = script_path.replace('"', "")
    ps_params = (
        "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden "
        f'-File "{safe_path}"'
    )

    if elevated:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            ps_exe,
            ps_params,
            cwd,
            SW_HIDE,
        )
        if rc <= 32:
            logger.warning("ShellExecuteW(runas) failed rc=%s ps=%s", rc, ps_exe)
            return False
        logger.info("Updater elevated helper started script=%s", safe_path)
        return True

    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "open",
        ps_exe,
        ps_params,
        cwd,
        SW_HIDE,
    )
    if rc > 32:
        logger.info(
            "Updater helper started (ShellExecute open) script=%s ps=%s",
            script_path,
            ps_exe,
        )
        return True

    logger.warning(
        "ShellExecuteW(open) failed rc=%s; trying subprocess (job-breakaway)", rc
    )

    try:
        subprocess.Popen(
            [
                ps_exe,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                script_path,
            ],
            cwd=cwd,
            close_fds=False,
            creationflags=HELPER_CREATION_FLAGS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(
            "Updater helper subprocess started (job-breakaway) script=%s",
            script_path,
        )
        return True
    except OSError as e:
        if getattr(e, "winerror", None) == 5:
            logger.warning(
                "CreateProcess denied breakaway (%s); will try cmd.exe start", e
            )
        else:
            logger.exception(
                "subprocess helper launch failed; will try cmd.exe start",
            )
    except Exception:
        logger.exception(
            "subprocess helper launch failed; will try cmd.exe start",
        )

    cmd_exe = os.path.join(winds, "System32", "cmd.exe")
    try:
        subprocess.Popen(
            [
                cmd_exe,
                "/c",
                "start",
                "",
                "/min",
                ps_exe,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                script_path,
            ],
            cwd=cwd,
            close_fds=False,
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(
            "Updater helper started via cmd.exe start script=%s", script_path
        )
        return True
    except Exception:
        logger.exception("cmd.exe start helper launch failed")

    logger.error("Could not launch update helper script=%s", script_path)
    return False


def apply_update(info, progress_cb=None):
    """Download the update package, verify it, and kick off the swap helper.

    Returns a (ok, message) tuple. On ok=True the caller should immediately
    exit the running app so the helper can replace the locked exe.
    """
    exe_path = _current_exe_path()
    if exe_path is None:
        return (False,
                "Auto-update only works when running the packaged Copasta.exe "
                "(you appear to be running from source).")

    install_dir = os.path.abspath(os.path.dirname(exe_path))
    exe_name = os.path.basename(exe_path)

    script_staging = _machine_staging_dir()
    logger.info("Updater: staging under %s (avoid cloud-sync locks beside Copasta.exe)", script_staging)

    install_writable = _test_dir_writable(install_dir)
    local_zip, local_sha = _find_local_update_zip(install_dir)

    zip_path = os.path.join(script_staging, "Copasta_update.zip")
    if local_zip:
        logger.info("Updater: using local test package %s", local_zip)
        shutil.copy2(local_zip, zip_path)
        sha_bytes = open(local_sha, "rb").read()
    else:
        try:
            _http_download(info.download_url, zip_path, progress_cb=progress_cb)
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            logger.exception("Update download failed")
            return (False, f"Download failed: {e}")
        try:
            sha_bytes = _http_get(info.sha256_url)
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            logger.exception("SHA-256 fetch failed")
            return (False, f"Could not fetch checksum: {e}")

    expected = _parse_sha256_file_bytes(sha_bytes)
    if not expected:
        return (False, "Checksum file is malformed; aborting update.")
    actual = _sha256_file(zip_path)
    if actual != expected:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return (False,
                "Downloaded zip failed integrity check (SHA-256 mismatch). "
                "Aborted for safety.")
    extract_root = os.path.join(script_staging, "copasta_extract")
    try:
        if os.path.isdir(extract_root):
            shutil.rmtree(extract_root, ignore_errors=True)
        pkg_dir = _extract_update_zip(zip_path, extract_root)
    except (OSError, ValueError) as e:
        logger.exception("Update zip extract failed")
        return (False, f"Could not unpack update: {e}")

    relaunch_script = _write_delayed_relaunch_script(
        script_staging, install_dir, exe_name,
    )
    script_path = _write_helper_script(
        script_staging,
        install_dir,
        exe_name,
        os.getpid(),
        relaunch_script,
        pkg_dir,
    )

    elevated = not install_writable
    logger.info(
        "Apply update: install_dir=%s writable=%s -> %s helper",
        install_dir, not elevated, "elevated" if elevated else "normal",
    )
    if not _launch_helper(script_path, elevated=elevated):
        if elevated:
            return (False,
                    "The update needs administrator permission to replace "
                    f"{exe_name} in:\n  {install_dir}\n\n"
                    "The UAC prompt was declined. Try again later, or move "
                    "Copasta to a folder you own.")
        return (False, "Could not launch the update helper.")

    return (True, "Updating now; Copasta will close and reopen.")


# ---------------------------------------------------------------------------
# UI: update dialog
#
# Shown on the Tk main thread. Returns one of "install", "later", "skip"
# via the on_choice callback.


def show_update_dialog(parent, info, on_install, on_later, on_skip,
                       current_version=None):
    """Modal-ish update dialog. Wires user choice to the callbacks."""
    win = ttk.Toplevel(parent) if hasattr(ttk, "Toplevel") else tk.Toplevel(parent)
    win.title("Copasta update available")
    try:
        win.configure(bg=_DARK_BG)
    except tk.TclError:
        pass
    try:
        win.transient(parent)
    except Exception:
        pass
    win.resizable(False, False)

    pad = {"padx": 14, "pady": 6}

    header = "A new version of Copasta is available"
    sub = "Version {} (you have {})".format(
        info.version, current_version or "an older version"
    )
    ttk.Label(win, text=header, font=("Segoe UI", 12, "bold")).pack(
        anchor=tk.W, padx=14, pady=(14, 2)
    )
    ttk.Label(win, text=sub).pack(anchor=tk.W, padx=14, pady=(0, 8))

    ttk.Label(win, text="What's new:").pack(anchor=tk.W, **pad)

    notes_frame = ttk.Frame(win)
    notes_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
    notes_text = tk.Text(
        notes_frame, width=64, height=10, wrap="word",
        bg="#2b2b2b", fg="#ffffff",
        insertbackground="#ffffff", relief=tk.FLAT, borderwidth=0,
        font=("Segoe UI", 9),
    )
    scroll = ttk.Scrollbar(notes_frame, command=notes_text.yview)
    notes_text.config(yscrollcommand=scroll.set)
    notes_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    notes_text.insert("1.0", info.notes or "(No release notes were provided.)")
    notes_text.config(state=tk.DISABLED)

    btn_row = ttk.Frame(win)
    btn_row.pack(fill=tk.X, padx=14, pady=(4, 14))

    def _choose(fn):
        try:
            win.destroy()
        except Exception:
            pass
        try:
            fn()
        except Exception:
            logger.exception("Update dialog callback raised")

    ttk.Button(btn_row, text="Skip this version",
               bootstyle="secondary",
               command=lambda: _choose(on_skip)).pack(side=tk.LEFT)
    ttk.Button(btn_row, text="Later",
               bootstyle="secondary",
               command=lambda: _choose(on_later)).pack(side=tk.LEFT, padx=(8, 0))
    ttk.Button(btn_row, text="Install now",
               bootstyle="success",
               command=lambda: _choose(on_install)).pack(side=tk.RIGHT)

    win.update_idletasks()
    try:
        parent.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, px)}+{max(0, py)}")
    except Exception:
        pass

    try:
        win.grab_set()
    except Exception:
        pass
    win.focus_force()

    win.after_idle(lambda: apply_dark_windows_titlebar(win))
    win.after(150, lambda: apply_dark_windows_titlebar(win))
    return win


def _show_progress_window(parent):
    """Tiny progress popup shown while downloading (dark themed)."""
    win = tk.Toplevel(parent)
    win.title("Updating Copasta")
    win.configure(bg=_DARK_BG)
    win.resizable(False, False)
    try:
        win.transient(parent)
    except Exception:
        pass

    frm = tk.Frame(win, bg=_DARK_BG, padx=24, pady=20)
    frm.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frm,
        text="Downloading update…",
        fg=_DARK_FG,
        bg=_DARK_BG,
        font=("Segoe UI", 11),
    ).pack()

    bar = ttk.Progressbar(
        frm, mode="determinate", length=320, maximum=100,
    )
    bar.pack(fill=tk.X, pady=(14, 8))

    pct = tk.Label(frm, text="", fg=_DARK_FG_DIM, bg=_DARK_BG, font=("Segoe UI", 9))
    pct.pack(pady=(2, 0))

    try:
        win.grab_set()
    except Exception:
        pass

    try:
        win.focus_force()
    except Exception:
        pass

    _center_on_parent_popup(parent, win)
    win.after_idle(lambda: apply_dark_windows_titlebar(win))
    win.after(150, lambda: apply_dark_windows_titlebar(win))
    return win, bar, pct


# ---------------------------------------------------------------------------
# Top-level orchestration


def _persist_skipped(settings_io, version):
    """Write skipped_update_version into settings via the provided IO callbacks."""
    try:
        s = settings_io.get_settings()
        s["skipped_update_version"] = version
        settings_io.save_settings(s)
    except Exception:
        logger.exception("Failed to persist skipped_update_version")


class SettingsIO:
    """Thin facade so updater doesn't need to know about data_model internals."""
    def __init__(self, get_settings, save_settings):
        self._get = get_settings
        self._save = save_settings

    def get_settings(self):
        return self._get() or {}

    def save_settings(self, s):
        self._save(s)


def _do_install(parent_root, info, on_finished):
    """Show progress, run apply_update on a worker thread, exit app on success."""
    progress_win, bar, pct_label = _show_progress_window(parent_root)

    def progress_cb(done, total):
        def update_ui():
            try:
                if total:
                    pct = min(100, int(done * 100 / total))
                    bar["value"] = pct
                    pct_label.config(text=f"{pct}%  ({done // 1024} KB / {total // 1024} KB)")
                else:
                    bar.config(mode="indeterminate")
                    bar.start(20)
                    pct_label.config(text=f"{done // 1024} KB")
            except Exception:
                pass
        try:
            parent_root.after(0, update_ui)
        except Exception:
            pass

    def worker():
        ok, msg = apply_update(info, progress_cb=progress_cb)

        def finish_ui():
            try:
                progress_win.destroy()
            except Exception:
                pass
            if ok:
                try:
                    _show_dark_message(
                        parent_root,
                        "Copasta update",
                        "The download finished. When the countdown completes, Copasta "
                        "quits so the updater can replace your Copasta folder. The new "
                        "version usually starts automatically after about 30–60 seconds.",
                        auto_close_seconds=10,
                        on_finished=on_finished,
                    )
                except Exception:
                    if on_finished:
                        try:
                            on_finished()
                        except Exception:
                            logger.exception("on_finished raised")
            else:
                try:
                    _show_dark_message(
                        parent_root,
                        "Copasta update failed",
                        msg,
                        is_error=True,
                    )
                except Exception:
                    pass

        try:
            parent_root.after(0, finish_ui)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def check_in_background(parent_root, current_version, settings_io,
                        on_update_quit_app=None):
    """Silent check on startup. If an update is found, show the dialog on the Tk thread."""
    def worker():
        try:
            skipped = settings_io.get_settings().get("skipped_update_version")
            info = check_for_update(current_version, skipped_version=skipped)
            if not info:
                return

            def show_dialog():
                show_update_dialog(
                    parent_root, info,
                    current_version=current_version,
                    on_install=lambda: _do_install(parent_root, info, on_update_quit_app),
                    on_later=lambda: None,
                    on_skip=lambda: _persist_skipped(settings_io, info.version),
                )
            parent_root.after(0, show_dialog)
        except Exception:
            logger.exception("Background update check crashed")

    threading.Thread(target=worker, daemon=True).start()


def check_now_interactive(parent_root, current_version, settings_io,
                          on_update_quit_app=None):
    """User-initiated check. Always reports a result."""
    busy_win = None
    try:
        busy_win = tk.Toplevel(parent_root)
        busy_win.title("Checking for updates")
        busy_win.configure(bg=_DARK_BG)
        busy_win.resizable(False, False)
        tk.Label(
            busy_win,
            text="Checking for updates…",
            fg=_DARK_FG,
            bg=_DARK_BG,
            font=("Segoe UI", 11),
        ).pack(padx=28, pady=26)
        try:
            busy_win.transient(parent_root)
            busy_win.grab_set()
        except Exception:
            pass
        _center_on_parent_popup(parent_root, busy_win)
        busy_win.after_idle(lambda: apply_dark_windows_titlebar(busy_win))
        busy_win.after(150, lambda: apply_dark_windows_titlebar(busy_win))
    except Exception:
        busy_win = None

    def worker():
        panic_err = None
        latest = None
        fetch_detail = None
        try:
            latest, fetch_detail = fetch_latest_release_ex()
        except Exception as e:
            panic_err = str(e)

        def finish_ui():
            try:
                if busy_win is not None:
                    busy_win.destroy()
            except Exception:
                pass
            if panic_err:
                _show_dark_message(
                    parent_root,
                    "Update check failed",
                    panic_err,
                    is_error=True,
                )
                return

            if latest is None:
                body = fetch_detail or (
                    "Copasta could not read the latest GitHub release. "
                    "See copasta.log for details."
                )
                _show_dark_message(
                    parent_root,
                    "Couldn't check for updates",
                    body,
                )
                return

            if compare_versions(latest.version, current_version) > 0:
                show_update_dialog(
                    parent_root, latest,
                    current_version=current_version,
                    on_install=lambda: _do_install(parent_root, latest, on_update_quit_app),
                    on_later=lambda: None,
                    on_skip=lambda: None,
                )
                return

            # We have a valid release from GitHub; only then is "up to date" meaningful.
            _show_dark_message(
                parent_root,
                "Up to date",
                "You're running the latest version "
                f"(Copasta {current_version}).",
            )

        try:
            parent_root.after(0, finish_ui)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()
