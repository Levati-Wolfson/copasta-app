"""
Copasta self-updater.

Checks the public GitHub Releases of Levati-Wolfson/copasta-app for a newer
version. If one is found and the user agrees, downloads the new Copasta.exe to
a temp folder, verifies its SHA-256 against a sibling .sha256 asset, then hands
off to a small PowerShell helper script that:

  1. Waits for the currently running Copasta.exe to exit (file lock to release).
  2. Replaces the old exe with the new one.
  3. Relaunches Copasta.
  4. Self-deletes.

If the install directory is not writable by the current user (e.g. Program
Files), the helper is launched elevated via UAC (ShellExecuteW "runas").

This module is dev-mode safe: when running from source (not a PyInstaller
bundle), apply_update() refuses and reports a friendly message.
"""

import ctypes
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
import tkinter as tk
from tkinter import messagebox
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
EXE_ASSET_NAME = "Copasta.exe"
SHA256_ASSET_NAME = "Copasta.exe.sha256"

HTTP_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 120
USER_AGENT = "Copasta-Updater"

logger = logging.getLogger(__name__)


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

    __slots__ = ("version", "tag", "exe_url", "sha256_url", "notes")

    def __init__(self, version, tag, exe_url, sha256_url, notes):
        self.version = version
        self.tag = tag
        self.exe_url = exe_url
        self.sha256_url = sha256_url
        self.notes = notes

    def __repr__(self):
        return f"UpdateInfo(version={self.version!r}, tag={self.tag!r})"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no `requests` dependency to keep the bundle slim)


def _ssl_context():
    """Default SSL context. Verifies certs. Uses system trust store on Windows."""
    return ssl.create_default_context()


def _http_get(url, timeout=HTTP_TIMEOUT_SECONDS, accept=None):
    """GET a URL with a User-Agent header. Returns the raw response bytes."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
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
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
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


def fetch_latest_release():
    """Return UpdateInfo for the latest release, or None on any failure."""
    try:
        data = _http_get_json(LATEST_RELEASE_API)
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.info("Update check: could not reach GitHub (%s)", e)
        return None
    except Exception:
        logger.exception("Update check: unexpected error fetching release")
        return None

    tag = data.get("tag_name") or ""
    version_tuple = parse_version(tag)
    if version_tuple is None:
        logger.warning("Update check: unparseable tag_name %r", tag)
        return None

    if data.get("draft") or data.get("prerelease"):
        logger.info("Update check: latest is draft/prerelease, ignoring")
        return None

    exe_url = _extract_asset_url(data, EXE_ASSET_NAME)
    sha_url = _extract_asset_url(data, SHA256_ASSET_NAME)
    if not exe_url:
        logger.warning("Update check: release %s has no %s asset", tag, EXE_ASSET_NAME)
        return None
    if not sha_url:
        logger.warning("Update check: release %s has no %s asset", tag, SHA256_ASSET_NAME)
        return None

    notes = render_release_notes(data.get("body") or "")
    version_str = "{}.{}.{}".format(*version_tuple)
    return UpdateInfo(
        version=version_str,
        tag=tag,
        exe_url=exe_url,
        sha256_url=sha_url,
        notes=notes,
    )


def check_for_update(current_version, skipped_version=None):
    """Return UpdateInfo if a strictly newer non-skipped release exists, else None."""
    info = fetch_latest_release()
    if info is None:
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


def _current_exe_path():
    """Path to the running Copasta.exe (or None when running from source)."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return None


# ---------------------------------------------------------------------------
# Self-update execution


_HELPER_PS1_TEMPLATE = r"""# Copasta self-updater helper. Auto-generated. Do not edit.
$ErrorActionPreference = 'Continue'
$installDir = '{install_dir}'
$oldExe     = Join-Path $installDir '{exe_name}'
$newExe     = '{new_exe}'
$logPath    = Join-Path $env:TEMP 'copasta_update.log'

function Log($msg) {{
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $logPath -Value "$stamp $msg"
}}

Log "Helper started. installDir=$installDir oldExe=$oldExe newExe=$newExe"

# Wait for the running Copasta to release its lock (up to 30s).
$deadline = (Get-Date).AddSeconds(30)
$replaced = $false
while ((Get-Date) -lt $deadline) {{
    try {{
        if (Test-Path -LiteralPath $oldExe) {{
            Remove-Item -LiteralPath $oldExe -Force -ErrorAction Stop
        }}
        Move-Item -LiteralPath $newExe -Destination $oldExe -Force -ErrorAction Stop
        $replaced = $true
        break
    }} catch {{
        Start-Sleep -Milliseconds 500
    }}
}}

if (-not $replaced) {{
    Log "Replace failed after timeout. Leaving downloaded exe in place."
    try {{
        $failed = Join-Path $installDir 'Copasta_failed_update.exe'
        if (Test-Path -LiteralPath $newExe) {{
            Move-Item -LiteralPath $newExe -Destination $failed -Force -ErrorAction SilentlyContinue
        }}
    }} catch {{ }}
    exit 1
}}

Log "Replace succeeded. Launching new exe."
try {{
    Start-Process -FilePath $oldExe
}} catch {{
    Log "Failed to launch new exe: $($_.Exception.Message)"
}}

# Self-delete (detached so we don't block the new process).
$selfPath = $MyInvocation.MyCommand.Path
Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile','-WindowStyle','Hidden','-Command',
    "Start-Sleep -Seconds 2; Remove-Item -LiteralPath `"$selfPath`" -Force -ErrorAction SilentlyContinue"
) -WindowStyle Hidden | Out-Null
"""


def _write_helper_script(install_dir, exe_name, new_exe_path):
    """Write a PowerShell script that performs the swap. Returns its path."""
    staging_dir = os.path.dirname(new_exe_path)
    script = _HELPER_PS1_TEMPLATE.format(
        install_dir=install_dir.replace("'", "''"),
        exe_name=exe_name.replace("'", "''"),
        new_exe=new_exe_path.replace("'", "''"),
    )
    script_path = os.path.join(staging_dir, "copasta_update.ps1")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    return script_path


def _launch_helper(script_path, elevated):
    """Launch the PowerShell helper. Returns True if it appears to have started."""
    args = (
        f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{script_path}"'
    )
    if elevated:
        SW_HIDE = 0
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe", args, None, SW_HIDE
        )
        if rc <= 32:
            logger.warning("ShellExecuteW elevation failed: rc=%s", rc)
            return False
        return True
    else:
        try:
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", script_path],
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                close_fds=True,
            )
            return True
        except Exception:
            logger.exception("Failed to launch updater helper.")
            return False


def apply_update(info, progress_cb=None):
    """Download the new exe, verify it, and kick off the swap helper.

    Returns a (ok, message) tuple. On ok=True the caller should immediately
    exit the running app so the helper can replace the locked exe.
    """
    exe_path = _current_exe_path()
    if exe_path is None:
        return (False,
                "Auto-update only works when running the packaged Copasta.exe "
                "(you appear to be running from source).")

    install_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)

    staging_dir = os.path.join(tempfile.gettempdir(), "copasta_update")
    try:
        os.makedirs(staging_dir, exist_ok=True)
    except OSError as e:
        return (False, f"Could not create staging folder: {e}")

    new_exe_path = os.path.join(staging_dir, "Copasta_new.exe")
    try:
        _http_download(info.exe_url, new_exe_path, progress_cb=progress_cb)
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

    actual = _sha256_file(new_exe_path)
    if actual != expected:
        try:
            os.remove(new_exe_path)
        except OSError:
            pass
        return (False,
                "Downloaded file failed integrity check (SHA-256 mismatch). "
                "Aborted for safety.")

    script_path = _write_helper_script(install_dir, exe_name, new_exe_path)

    elevated = not _test_dir_writable(install_dir)
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
    return win


def _show_progress_window(parent):
    """Tiny indeterminate progress popup shown while downloading."""
    win = ttk.Toplevel(parent) if hasattr(ttk, "Toplevel") else tk.Toplevel(parent)
    win.title("Updating Copasta")
    win.resizable(False, False)
    try:
        win.transient(parent)
    except Exception:
        pass
    ttk.Label(win, text="Downloading update…").pack(padx=20, pady=(16, 8))
    bar = ttk.Progressbar(win, mode="determinate", length=320, maximum=100)
    bar.pack(padx=20, pady=(0, 12))
    pct = ttk.Label(win, text="")
    pct.pack(padx=20, pady=(0, 16))

    win.update_idletasks()
    try:
        px = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, px)}+{max(0, py)}")
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass
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
                    messagebox.showinfo(
                        "Copasta is updating",
                        "Copasta will close in a moment, then reopen as the new version.",
                        parent=parent_root,
                    )
                except Exception:
                    pass
                if on_finished:
                    try:
                        on_finished()
                    except Exception:
                        logger.exception("on_finished raised")
            else:
                try:
                    messagebox.showerror(
                        "Copasta update failed", msg, parent=parent_root,
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
        busy_win = ttk.Toplevel(parent_root) if hasattr(ttk, "Toplevel") else tk.Toplevel(parent_root)
        busy_win.title("Checking for updates")
        busy_win.resizable(False, False)
        ttk.Label(busy_win, text="Checking for updates…").pack(padx=24, pady=20)
        try:
            busy_win.transient(parent_root)
            busy_win.grab_set()
        except Exception:
            pass
        busy_win.update_idletasks()
        try:
            px = parent_root.winfo_rootx() + (parent_root.winfo_width() - busy_win.winfo_width()) // 2
            py = parent_root.winfo_rooty() + (parent_root.winfo_height() - busy_win.winfo_height()) // 3
            busy_win.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass
    except Exception:
        busy_win = None

    def worker():
        info = None
        latest = None
        error = None
        try:
            latest = fetch_latest_release()
            if latest and compare_versions(latest.version, current_version) > 0:
                info = latest
        except Exception as e:
            error = str(e)

        def finish_ui():
            try:
                if busy_win is not None:
                    busy_win.destroy()
            except Exception:
                pass
            if error:
                messagebox.showerror(
                    "Update check failed",
                    f"Could not reach GitHub:\n{error}",
                    parent=parent_root,
                )
                return
            if info:
                show_update_dialog(
                    parent_root, info,
                    current_version=current_version,
                    on_install=lambda: _do_install(parent_root, info, on_update_quit_app),
                    on_later=lambda: None,
                    on_skip=lambda: None,  # manual check: don't persist skip
                )
                return
            if latest is None:
                messagebox.showinfo(
                    "Up to date",
                    "Couldn't reach GitHub to check for updates. "
                    "Check your internet connection and try again.",
                    parent=parent_root,
                )
            else:
                messagebox.showinfo(
                    "Up to date",
                    f"You're running the latest version (Copasta {current_version}).",
                    parent=parent_root,
                )

        try:
            parent_root.after(0, finish_ui)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()
