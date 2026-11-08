# PyInstaller spec — build with: pyinstaller shujaa.spec
import sys

a = Analysis(
    ["desktop.py"],
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=["waitress", "flask"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="shujaa-pos",
    console=False,
)
if sys.platform == "darwin":
    app = BUNDLE(exe, name="ShujaaPOS.app", bundle_identifier="app.shujaa.pos")
