from pathlib import Path

# PyInstaller resolves relative Analysis/datas paths from the spec working
# directory, which build-mcp fixes to src/backend. Keep the repository root
# explicit so Windows and POSIX builds select the same tracked sources.
repo_root = Path(SPECPATH).resolve().parents[2]
scripts_dir = repo_root / "scripts"

adapter = scripts_dir / "growthmap_mcp.py"
schemas = scripts_dir / "growthmap_mcp_schemas.json"
credential = scripts_dir / "growthmap_credential.py"
for required in (adapter, schemas, credential):
    if not required.is_file():
        raise SystemExit(f"required MCP source missing: {required}")

a=Analysis(
    [str(adapter)],
    pathex=[str(repo_root), str(scripts_dir)],
    datas=[(str(schemas),'.')],
    hiddenimports=['growthmap_credential'],
)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='growthmap-mcp',console=True)
