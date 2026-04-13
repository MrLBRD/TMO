# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

cv2_binaries = collect_dynamic_libs("cv2")
numpy_binaries = collect_dynamic_libs("numpy")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=cv2_binaries + numpy_binaries,
    datas=[],
    hiddenimports=[
        'PIL._tkinter_finder',
        'pyzbar.pyzbar',
        'pyzbar.wrapper',
        'customtkinter',
        'cv2',
        'requests',
        'urllib3',
        'charset_normalizer',
        'certifi',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'scipy',
        'pandas',
        'pytest',
        'notebook',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='TMO',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Pas de console Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Ajoutez un chemin d'icône si vous en avez une
)
