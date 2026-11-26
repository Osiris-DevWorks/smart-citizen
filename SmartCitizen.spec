# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Smart Citizen
import os

# This version's release notes, for the What's New dialog after an install or
# update; left out when not written yet. Mirrors scripts/build/build_exe.py.
with open(os.path.join(SPECPATH, 'VERSION.TXT')) as _f:
    _version = _f.read().strip()
_release_notes = f'docs/{_version}-RELEASE-NOTES.md'
_extra_docs = [(_release_notes, 'docs')] if os.path.isfile(os.path.join(SPECPATH, _release_notes)) else []

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('VERSION.TXT', '.'),
        ('docs/ABOUT.md', 'docs'),
        ('docs/HELP.md', 'docs'),
        ('docs/LEGAL.md', 'docs'),
        ('docs/FAQ.md', 'docs'),
        ('assets', 'assets'),
        ('patches', 'patches'),
        ('languages', 'languages'),
        ('scripts/generate_enhancements_ini.py', 'scripts'),
    ] + _extra_docs,
    # `scripts/generate_enhancements_ini.py` is bundled as a data file (not
    # analyzed as a Python module), so PyInstaller doesn't follow its
    # imports. Without this hint its `from src.utils.progress_sink import
    # ProgressSink` silently hits the `except ImportError: _sink = None`
    # branch in the frozen build and the Generate Enhancements run shows an
    # indeterminate bar the whole time even though the determinate-progress
    # plumbing is otherwise intact. dataforge_patcher survives by accident
    # because main_window.py also imports it for apply_patches; listed here
    # as belt + suspenders so a future main_window refactor can't break it.
    hiddenimports=[
        'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
        'src.utils.progress_sink',
        'src.utils.dataforge_patcher',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SmartCitizen',
    icon='assets/logo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartCitizen',
)
