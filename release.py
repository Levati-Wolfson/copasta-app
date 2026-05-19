"""
One-command Copasta release tool.

Typical usage (run by the AI agent when you say "release 6.22"):

    python release.py 6.22 --notes-file release_notes.txt

Steps performed, in order:

    1. Validate args, version string, and that the working tree is clean.
    2. Rewrite _version.py with the new version.
    3. Build dist/Copasta/ (onedir) with PyInstaller (copasta.spec).
    4. Zip dist/Copasta/ -> dist/Copasta.zip; SHA-256 -> dist/Copasta.zip.sha256.
    5. git add _version.py && git commit -m "Release v<ver>" && git tag v<ver>.
    6. git push origin <branch> && git push origin v<ver>.
    7. gh release create v<ver> --title "Copasta <ver>" --notes-file <...>
       and upload Copasta.zip + Copasta.zip.sha256.

Flags:
    --notes "..."         Inline release notes (short).
    --notes-file PATH     Path to a text file with release notes.
    --dry-run             Print what would happen; don't push or publish.
    --allow-dirty         Skip the clean-working-tree check.
    --skip-build          Reuse the existing dist/Copasta.zip (and onedir folder).

Requires on PATH: python, git, pyinstaller (or `python -m PyInstaller`),
and the GitHub CLI (`gh`), authenticated for Levati-Wolfson/copasta-app.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

# --- Config -----------------------------------------------------------------

PROJECT_ROOT   = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE   = os.path.join(PROJECT_ROOT, "_version.py")
SPEC_FILE      = os.path.join(PROJECT_ROOT, "copasta.spec")
DIST_DIR       = os.path.join(PROJECT_ROOT, "dist")
APP_DIR_NAME   = "Copasta"
APP_DIR        = os.path.join(DIST_DIR, APP_DIR_NAME)
EXE_NAME       = "Copasta.exe"
EXE_PATH       = os.path.join(APP_DIR, EXE_NAME)
ZIP_NAME       = "Copasta.zip"
ZIP_PATH       = os.path.join(DIST_DIR, ZIP_NAME)
SHA_PATH       = ZIP_PATH + ".sha256"

GH_OWNER       = "Levati-Wolfson"
GH_REPO        = "copasta-app"
GH_NWO         = f"{GH_OWNER}/{GH_REPO}"

VERSION_RE     = re.compile(r"^\d+\.\d+(?:\.\d+)?$")  # 6.22 or 6.22.1

# --- Small utilities --------------------------------------------------------


class ReleaseError(Exception):
    pass


def info(msg):
    print(f"[release] {msg}", flush=True)


def warn(msg):
    print(f"[release][warn] {msg}", flush=True)


def run(cmd, cwd=PROJECT_ROOT, check=True, capture=False, env=None):
    """Run a subprocess. Returns CompletedProcess. Streams output unless capture=True."""
    info("$ " + (" ".join(_q(c) for c in cmd) if isinstance(cmd, list) else cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        env=env,
        shell=isinstance(cmd, str),
    )


def _q(s):
    s = str(s)
    return f'"{s}"' if " " in s else s


def which(name):
    return shutil.which(name)


# --- Steps ------------------------------------------------------------------


def validate_version(v):
    if not VERSION_RE.match(v):
        raise ReleaseError(
            f"Bad version {v!r}. Expected MAJOR.MINOR or MAJOR.MINOR.PATCH "
            "(e.g. 6.22 or 6.22.1)."
        )


def ensure_tools(skip_build):
    missing = []
    if which("git") is None:
        missing.append("git")
    if which("gh") is None:
        missing.append("gh (GitHub CLI)")
    if not skip_build:
        if which("pyinstaller") is None:
            # Try via python -m
            r = subprocess.run(
                [sys.executable, "-m", "PyInstaller", "--version"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                missing.append("pyinstaller (pip install pyinstaller)")
    if missing:
        raise ReleaseError("Missing required tools: " + ", ".join(missing))


def ensure_gh_auth():
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode != 0:
        raise ReleaseError(
            "GitHub CLI is not authenticated. Run `gh auth login` and try again."
        )


def ensure_clean_tree(allow_dirty):
    r = run(["git", "status", "--porcelain"], capture=True)
    if r.stdout.strip() and not allow_dirty:
        raise ReleaseError(
            "Working tree is not clean:\n"
            + r.stdout
            + "\nCommit or stash changes, or pass --allow-dirty."
        )


def current_branch():
    r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return r.stdout.strip()


def read_current_version():
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise ReleaseError(f"Could not find __version__ in {VERSION_FILE}")
    return m.group(1)


def write_version(new_version):
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    new_text, n = re.subn(
        r'(__version__\s*=\s*")[^"]+(")',
        r"\g<1>" + new_version + r"\g<2>",
        text,
        count=1,
    )
    if n != 1:
        raise ReleaseError(f"Failed to update __version__ in {VERSION_FILE}")
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(new_text)
    info(f"Wrote version {new_version} to {VERSION_FILE}")


def ensure_tag_unused(tag):
    # Local
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if r.returncode == 0:
        raise ReleaseError(f"Git tag {tag} already exists locally. Aborting.")
    # Remote
    r = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", tag],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if r.returncode == 0 and r.stdout.strip():
        raise ReleaseError(f"Git tag {tag} already exists on origin. Aborting.")


def build_exe():
    import zipfile

    info("Building Copasta (onedir) with PyInstaller (this can take 30-90s)...")
    cmd = ["pyinstaller", "--noconfirm", "--clean", SPEC_FILE]
    if which("pyinstaller") is None:
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC_FILE]
    run(cmd)
    if not os.path.isfile(EXE_PATH):
        raise ReleaseError(f"Build finished but {EXE_PATH} is missing.")
    internal = os.path.join(APP_DIR, "_internal")
    if not os.path.isdir(internal):
        raise ReleaseError(f"Build finished but {internal} is missing (onedir layout).")

    info(f"Zipping {APP_DIR} -> {ZIP_PATH} ...")
    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(APP_DIR):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.join(APP_DIR_NAME, os.path.relpath(full, APP_DIR))
                zf.write(full, arc.replace("\\", "/"))

    size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    info(f"Built {EXE_PATH} and {ZIP_PATH} ({size_mb:.1f} MB zip)")


def write_sha256():
    h = hashlib.sha256()
    with open(ZIP_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with open(SHA_PATH, "w", encoding="utf-8") as f:
        f.write(f"{digest}  {ZIP_NAME}\n")
    info(f"SHA-256: {digest}")
    info(f"Wrote {SHA_PATH}")
    return digest


def git_commit_and_tag(new_version, tag, dry_run):
    run(["git", "add", VERSION_FILE])
    msg = f"Release {tag}"
    if dry_run:
        info(f"[dry-run] would: git commit -m {msg!r} && git tag {tag}")
        return
    run(["git", "commit", "-m", msg])
    run(["git", "tag", tag])


def git_push(branch, tag, dry_run):
    if dry_run:
        info(f"[dry-run] would: git push origin {branch} && git push origin {tag}")
        return
    run(["git", "push", "origin", branch])
    run(["git", "push", "origin", tag])


def gh_create_release(tag, new_version, notes_file, dry_run):
    title = f"Copasta {new_version}"
    cmd = [
        "gh", "release", "create", tag,
        "--repo", GH_NWO,
        "--title", title,
        "--notes-file", notes_file,
        ZIP_PATH,
        SHA_PATH,
    ]
    if dry_run:
        info(f"[dry-run] would: {' '.join(_q(c) for c in cmd)}")
        return
    run(cmd)


# --- Main -------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="Cut a Copasta release.")
    ap.add_argument("version", help="New version (e.g. 6.22 or 6.22.1)")
    notes_group = ap.add_mutually_exclusive_group(required=True)
    notes_group.add_argument("--notes", help="Inline release notes")
    notes_group.add_argument("--notes-file", help="Path to release notes file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="Skip the 'working tree clean' check.")
    ap.add_argument("--skip-build", action="store_true",
                    help="Reuse existing dist/Copasta/ and Copasta.zip.")
    args = ap.parse_args()

    new_version = args.version.strip().lstrip("v")
    tag = "v" + new_version
    validate_version(new_version)

    info(f"Releasing Copasta {new_version} (tag {tag})")

    ensure_tools(args.skip_build)
    ensure_gh_auth()
    ensure_clean_tree(args.allow_dirty)
    branch = current_branch()
    info(f"Current branch: {branch}")
    ensure_tag_unused(tag)

    cur = read_current_version()
    info(f"Current version (in _version.py): {cur}")
    if cur == new_version and not args.allow_dirty:
        raise ReleaseError(
            f"_version.py already says {cur}. Pass --allow-dirty if you really "
            "mean to re-release the same version."
        )

    # Stage release notes into a temp file (gh wants a path).
    if args.notes_file:
        notes_path = os.path.abspath(args.notes_file)
        if not os.path.isfile(notes_path):
            raise ReleaseError(f"Notes file does not exist: {notes_path}")
        cleanup_notes = False
    else:
        fd, notes_path = tempfile.mkstemp(prefix="copasta_notes_", suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(args.notes.strip() + "\n")
        cleanup_notes = True

    try:
        write_version(new_version)

        if args.skip_build:
            if not os.path.isfile(EXE_PATH):
                raise ReleaseError(f"--skip-build set but {EXE_PATH} does not exist.")
            info(f"Reusing existing {EXE_PATH}")
        else:
            build_exe()

        digest = write_sha256()

        git_commit_and_tag(new_version, tag, args.dry_run)
        git_push(branch, tag, args.dry_run)
        gh_create_release(tag, new_version, notes_path, args.dry_run)

        info("")
        info("================================================================")
        info(f"  Released Copasta {new_version} ({tag})")
        info(f"  SHA-256: {digest}")
        if args.dry_run:
            info("  (dry-run: nothing was pushed or published)")
        else:
            info(f"  https://github.com/{GH_NWO}/releases/tag/{tag}")
        info("================================================================")
    finally:
        if cleanup_notes:
            try:
                os.remove(notes_path)
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except ReleaseError as e:
        print(f"[release][error] {e}", file=sys.stderr)
        sys.exit(2)
    except subprocess.CalledProcessError as e:
        cmd = e.cmd if isinstance(e.cmd, str) else " ".join(str(c) for c in e.cmd)
        print(f"[release][error] command failed: {cmd}", file=sys.stderr)
        sys.exit(e.returncode or 1)
    except KeyboardInterrupt:
        print("[release] aborted by user", file=sys.stderr)
        sys.exit(130)
