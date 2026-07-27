# PyInstaller spec: invoke from src/backend with packaging/build-sidecar scripts.
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('uvicorn') + collect_submodules('sqlalchemy') + collect_submodules('aiosqlite') + collect_submodules('fastapi')
a = Analysis(['sidecar_entry.py'], pathex=['..'], hiddenimports=hiddenimports, datas=[('../desktop/license_public_key.pem','desktop')])
pyz = PYZ(a.pure)
# The same binary exposes a maintenance CLI whose JSON result is read over stdout.
# Electron starts it with windowsHide=true, so console=True preserves CLI semantics
# without displaying a console window in normal desktop operation.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='growthmap-sidecar', console=True)
