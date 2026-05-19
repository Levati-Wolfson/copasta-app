# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

SPEC_ROOT = os.path.abspath(SPECPATH)

_PY_DIR = os.path.dirname(sys.executable)
_EXTRA_BINARIES = []
for _dll in ('vcruntime140.dll', 'vcruntime140_1.dll', 'python3.dll'):
    _p = os.path.join(_PY_DIR, _dll)
    if os.path.isfile(_p):
        _EXTRA_BINARIES.append((_p, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_EXTRA_BINARIES,
    datas=[
        (os.path.join(SPEC_ROOT, 'Newicon.png'), '.'),
    ],
    hiddenimports=[
        'pynput',
        'pynput.keyboard',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageTk',
        'app_icon',
        'win32clipboard',
        'win32con',
        'win32api',
        'pywintypes',
        'pythoncom',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['chaos_monkey'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Onedir layout: Copasta.exe + _internal/ (python313.dll on disk — no _MEI extract).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Copasta',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPEC_ROOT, 'Newicon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Copasta',
)
