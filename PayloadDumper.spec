# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['payload_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('update_metadata_pb2.py', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['fsspec', 'aiohttp', 'requests', 'cryptography', 'lxml', 'tzdata', 'boto3', 'botocore', 's3fs', 'gcsfs', 'paramiko', 'adlfs', 'pandas', 'numpy', 'scipy', 'matplotlib', 'PIL', 'tkinter', '_tkinter', 'test', 'unittest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PayloadDumper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
