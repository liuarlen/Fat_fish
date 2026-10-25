import os

from PyInstaller.utils.hooks import collect_all

base = globals().get("SPECPATH") or os.path.dirname(os.path.abspath(__file__))
base = os.path.abspath(base)

datas = [
    (os.path.join(base, "resources"), "resources"),
    (os.path.join(base, "packaging", "使用说明.txt"), "."),
]
binaries = []
hiddenimports = []

# PyMuPDF 的扩展和 mupdfcpp64.dll 不一定会被自动收集
pymupdf_datas, pymupdf_binaries, pymupdf_hidden = collect_all("pymupdf")
datas += [item for item in pymupdf_datas if "mupdf-devel" not in item[0]]
binaries += pymupdf_binaries
hiddenimports += pymupdf_hidden

# requests 的证书包
try:
    from PyInstaller.utils.hooks import collect_data_files
    datas += collect_data_files("certifi")
except Exception:
    pass

hiddenimports += ["fitz", "pymupdf", "pymupdf._extra"]

a = Analysis(
    ["app.py"],
    pathex=[base],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fat_fish",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(base, "resources", "app.ico"),
    version=os.path.join(base, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Fat_fish",
)
