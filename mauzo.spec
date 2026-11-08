# PyInstaller spec — build with: pyinstaller mauzo.spec
import sys

a = Analysis(
    ["desktop.py"],
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=["waitress", "flask"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="mauzo-pos",
    console=False,
)
if sys.platform == "darwin":
    app = BUNDLE(exe, name="Mauzo POS.app", bundle_identifier="app.mauzo.pos")
