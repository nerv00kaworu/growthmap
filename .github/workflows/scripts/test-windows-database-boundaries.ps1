$ErrorActionPreference = 'Stop'

$root = Join-Path $env:RUNNER_TEMP ("growthmap-db-boundaries-{0}" -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $root | Out-Null
$sidecar = (Resolve-Path 'desktop/dist/win-unpacked/resources/sidecar/growthmap-sidecar.exe').Path
$fixture = Join-Path $root 'fixture.db'
$env:GROWTHMAP_DESKTOP_MODE = '1'

python desktop/scripts/create-e2e-fixture.py $fixture
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $fixture -PathType Leaf)) {
  throw 'Valid fixture creation failed'
}

function Invoke-ExpectedMaintenanceRejection {
  param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Label)

  & $sidecar --validate-db $Source *> $null
  if ($LASTEXITCODE -eq 0) { throw "${Label}: --validate-db unexpectedly accepted the unsafe path" }

  $destination = Join-Path $root ("{0}-snapshot.db" -f $Label)
  $env:GROWTHMAP_MAINTENANCE_DESTINATION = $destination
  & $sidecar --validated-snapshot-db $Source *> $null
  if ($LASTEXITCODE -eq 0) { throw "${Label}: --validated-snapshot-db unexpectedly accepted the unsafe path" }
  if (Test-Path $destination) { throw "${Label}: rejected snapshot left a destination behind" }
  Write-Host "PASS expected rejection: $Label"
}

# A valid SQLite fixture with a second directory entry must fail both maintenance paths.
$hardlink = Join-Path $root 'fixture-hardlink.db'
New-Item -ItemType HardLink -Path $hardlink -Target $fixture | Out-Null
if ((Get-Item $hardlink).LinkType -ne 'HardLink') { throw 'Hardlink evidence was not actually created' }
Invoke-ExpectedMaintenanceRejection -Source $hardlink -Label 'hardlink'
Remove-Item -LiteralPath $hardlink -Force
if ((Get-Item $fixture).LinkType -eq 'HardLink') { throw 'Hardlink cleanup did not restore the fixture to one link' }

# Exercise traversal through a genuine FILE_ATTRIBUTE_REPARSE_POINT. No capability skip is allowed.
$junctionTarget = Join-Path $root 'junction-target'
$junction = Join-Path $root 'fixture-junction'
New-Item -ItemType Directory -Path $junctionTarget | Out-Null
Copy-Item $fixture (Join-Path $junctionTarget 'fixture.db')
try {
  New-Item -ItemType Junction -Path $junction -Target $junctionTarget | Out-Null
} catch {
  throw "Windows runner could not create the required directory junction: $($_.Exception.Message)"
}
$junctionItem = Get-Item $junction
if (($junctionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
  throw 'Created junction does not carry FILE_ATTRIBUTE_REPARSE_POINT'
}
Write-Host "Junction attributes verified: $($junctionItem.Attributes)"
Invoke-ExpectedMaintenanceRejection -Source (Join-Path $junction 'fixture.db') -Label 'junction-traversal'

# This is UNC-shaped but points only at localhost. Production maintenance must reject it before open.
$unc = '\\localhost\growthmap-path-policy-evidence\fixture.db'
Invoke-ExpectedMaintenanceRejection -Source $unc -Label 'unc-shaped-localhost'

# The temp-only harness imports the production database manager and drives its packaged maintenance path.
$env:GM_BOUNDARY_ROOT = $root
$env:GM_BOUNDARY_SIDECAR = $sidecar
$env:GM_BOUNDARY_FIXTURE = $fixture
node .github/workflows/scripts/test-windows-recovery-matrix.js
if ($LASTEXITCODE -ne 0) { throw 'Crash-residue recovery matrix failed' }

Write-Host "Windows database boundary evidence passed in $root"
