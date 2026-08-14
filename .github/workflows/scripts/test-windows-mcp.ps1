param([string]$McpExe = 'src/backend/dist/growthmap-mcp.exe')
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $McpExe).Path
$harness = (Resolve-Path '.github/workflows/scripts/test-windows-mcp.py').Path
# setup-python is the already-provisioned CI interpreter; the harness itself is stdlib-only.
python $harness --exe $exe
if ($LASTEXITCODE -ne 0) { throw "Windows MCP integration harness failed with exit code $LASTEXITCODE" }
