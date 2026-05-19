"""
Build update_test_build\\Copasta\\ as a fake old release (default 1.0), copy
Copasta.zip for local update testing, then restore _version.py and rebuild dist.

Usage (from repo root):

    python tools/build_update_test_build.py
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys

PROJECT = pathlib.Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT / "_version.py"
SPEC = PROJECT / "copasta.spec"
DIST_APP = PROJECT / "dist" / "Copasta"
DIST_ZIP = PROJECT / "dist" / "Copasta.zip"
DIST_ZIP_SHA = DIST_ZIP.with_name("Copasta.zip.sha256")
TEST_DIR = PROJECT / "update_test_build"
TEST_APP_DIR = TEST_DIR / "Copasta"
TEST_ZIP = TEST_DIR / "Copasta.zip"
TEST_ZIP_SHA = TEST_DIR / "Copasta.zip.sha256"

_VERSION_LINE = re.compile(
    r"^(__version__\s*=\s*[\"'])([^\"']+)([\"']\s*)$",
    re.MULTILINE,
)


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _set_version(contents: str, new_ver: str) -> str:
    m = _VERSION_LINE.search(contents)
    if not m:
        raise SystemExit(f"Could not find __version__ line in {VERSION_FILE}")
    return contents[: m.start()] + m.group(1) + new_ver + m.group(3) + contents[m.end() :]


def _run_pyinstaller(*, clean=False) -> None:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC.relative_to(PROJECT)),
        "--noconfirm",
    ]
    if clean:
        cmd.append("--clean")
    print("[build_update_test_build] " + " ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT)


def _write_dist_zip() -> None:
    import zipfile

    if DIST_ZIP.is_file():
        DIST_ZIP.unlink()
    with zipfile.ZipFile(DIST_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(DIST_APP):
            for name in files:
                full = pathlib.Path(root) / name
                arc = pathlib.Path("Copasta", full.relative_to(DIST_APP))
                zf.write(full, arc.as_posix())
    digest = _sha256_file(DIST_ZIP)
    DIST_ZIP_SHA.write_text(f"{digest}  Copasta.zip\n", encoding="utf-8")


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_app_tree(src: pathlib.Path, dest: pathlib.Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def main(argv: list[str]) -> int:
    fake_ver = argv[1] if len(argv) > 1 else "1.0"

    vc = _read_text(VERSION_FILE)
    m = _VERSION_LINE.search(vc)
    if not m:
        print(f"Missing __version__ in {VERSION_FILE}", file=sys.stderr)
        return 1
    real_ver = m.group(2)

    TEST_DIR.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[build_update_test_build] packaging fake {fake_ver} -> {TEST_APP_DIR}")
        VERSION_FILE.write_text(_set_version(vc, fake_ver), encoding="utf-8")
        _run_pyinstaller()
        if not (DIST_APP / "Copasta.exe").is_file():
            raise SystemExit(f"Missing {DIST_APP / 'Copasta.exe'} after build")
        _copy_app_tree(DIST_APP, TEST_APP_DIR)

        print(f"[build_update_test_build] restoring real {real_ver}, rebuilding dist")
        VERSION_FILE.write_text(_set_version(_read_text(VERSION_FILE), real_ver), encoding="utf-8")
        _run_pyinstaller(clean=True)
        _write_dist_zip()

        shutil.copy2(DIST_ZIP, TEST_ZIP)
        shutil.copy2(DIST_ZIP_SHA, TEST_ZIP_SHA)
    except BaseException:
        try:
            VERSION_FILE.write_text(vc, encoding="utf-8")
        except OSError:
            pass
        raise

    print(f"[build_update_test_build] Done. Run: {TEST_APP_DIR / 'Copasta.exe'}")
    print(f"[build_update_test_build] Local update zip: {TEST_ZIP}")
    print(f"[build_update_test_build] Latest dist zip: {DIST_ZIP} (__version__ = {real_ver})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
