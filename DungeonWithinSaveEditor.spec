# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Dungeon Within Save Editor (one-file, windowed)."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('frida')
datas = list(datas) + [
    ('tools/parts_catalog.json', '.'),
    ('tools/facility_catalog.json', '.'),
    ('tools/facility_prefixes.json', '.'),
    ('vendor', 'vendor'),
]

a = Analysis(
    ['tools/dw_save_gui.py'],
    pathex=['tools'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DungeonWithinSaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
