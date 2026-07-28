$ErrorActionPreference = 'Stop'

function Get-CanonicalPath {
  param([Parameter(Mandatory)][string]$Path)
  return [System.IO.Path]::GetFullPath($Path).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
  )
}

function Test-CanonicalChildPath {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Parent
  )

  $canonicalPath = Get-CanonicalPath $Path
  $canonicalParent = Get-CanonicalPath $Parent
  $prefix = $canonicalParent + [System.IO.Path]::DirectorySeparatorChar
  return $canonicalPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-SystemTempChild {
  param([Parameter(Mandatory)][string]$Path)
  if (-not (Test-CanonicalChildPath -Path $Path -Parent $systemTemp)) {
    throw "Boundary artifact path escaped the system temp directory: $Path"
  }
}

# RUNNER_TEMP can be configured beneath the checkout. The fixture generator's
# security contract is the OS temp directory, so derive the boundary root from
# the same API as Python's tempfile.gettempdir() and verify it canonically.
$systemTemp = Get-CanonicalPath ([System.IO.Path]::GetTempPath())
$repositoryRoot = Get-CanonicalPath (Resolve-Path '.').Path
$root = Join-Path $systemTemp ("growthmap-db-boundaries-{0}" -f [guid]::NewGuid())
Assert-SystemTempChild $root
if (Test-CanonicalChildPath -Path $root -Parent $repositoryRoot) {
  throw "Boundary root must not be inside the repository: $root"
}

$sidecar = (Resolve-Path 'desktop/dist/win-unpacked/resources/sidecar/growthmap-sidecar.exe').Path
$fixture = Join-Path $root 'fixture.db'
$repoFixture = Join-Path $repositoryRoot ("fixture-boundary-refusal-{0}.db" -f [guid]::NewGuid())
$junction = $null
$env:GROWTHMAP_DESKTOP_MODE = '1'

try {
  New-Item -ItemType Directory -Path $root | Out-Null
  Assert-SystemTempChild $fixture

  # Keep an executable contract that the hardened fixture helper rejects a
  # fresh output path in the checkout, including checkout paths with spaces.
  & python 'desktop/scripts/create-e2e-fixture.py' $repoFixture *> $null
  if ($LASTEXITCODE -eq 0) { throw 'Fixture helper unexpectedly accepted a repository output path' }
  if (Test-Path -LiteralPath $repoFixture) { throw 'Rejected repository fixture path was created' }
  Write-Host 'PASS fixture helper rejected repository output path'

  & python 'desktop/scripts/create-e2e-fixture.py' $fixture
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $fixture -PathType Leaf)) {
    throw 'Valid fixture creation failed'
  }

  function Invoke-ExpectedMaintenanceRejection {
    param([Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$Label)

    & $sidecar --validate-db $Source *> $null
    if ($LASTEXITCODE -eq 0) { throw "${Label}: --validate-db unexpectedly accepted the unsafe path" }

    $destination = Join-Path $root ("{0}-snapshot.db" -f $Label)
    Assert-SystemTempChild $destination
    $env:GROWTHMAP_MAINTENANCE_DESTINATION = $destination
    & $sidecar --validated-snapshot-db $Source *> $null
    if ($LASTEXITCODE -eq 0) { throw "${Label}: --validated-snapshot-db unexpectedly accepted the unsafe path" }
    if (Test-Path -LiteralPath $destination) { throw "${Label}: rejected snapshot left a destination behind" }
    Write-Host "PASS expected rejection: $Label"
  }

  # A valid SQLite fixture with a second directory entry must fail both maintenance paths.
  $hardlink = Join-Path $root 'fixture-hardlink.db'
  Assert-SystemTempChild $hardlink
  New-Item -ItemType HardLink -Path $hardlink -Target $fixture | Out-Null
  if ((Get-Item -LiteralPath $hardlink).LinkType -ne 'HardLink') { throw 'Hardlink evidence was not actually created' }
  Invoke-ExpectedMaintenanceRejection -Source $hardlink -Label 'hardlink'
  Remove-Item -LiteralPath $hardlink -Force
  if ((Get-Item -LiteralPath $fixture).LinkType -eq 'HardLink') { throw 'Hardlink cleanup did not restore the fixture to one link' }

  # Exercise traversal through a genuine FILE_ATTRIBUTE_REPARSE_POINT. No capability skip is allowed.
  $junctionTarget = Join-Path $root 'junction-target'
  $junction = Join-Path $root 'fixture-junction'
  Assert-SystemTempChild $junctionTarget
  Assert-SystemTempChild $junction
  New-Item -ItemType Directory -Path $junctionTarget | Out-Null
  Copy-Item -LiteralPath $fixture -Destination (Join-Path $junctionTarget 'fixture.db')
  try {
    New-Item -ItemType Junction -Path $junction -Target $junctionTarget | Out-Null
  } catch {
    throw "Windows runner could not create the required directory junction: $($_.Exception.Message)"
  }
  $junctionItem = Get-Item -LiteralPath $junction
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
  & node '.github/workflows/scripts/test-windows-recovery-matrix.js'
  if ($LASTEXITCODE -ne 0) { throw 'Crash-residue recovery matrix failed' }

  Write-Host "Windows database boundary evidence passed in $root"
} finally {
  # Remove the reparse point itself before recursively removing its temp root;
  # never permit cleanup to follow a junction target.
  if ($junction -and (Test-Path -LiteralPath $junction)) {
    Remove-Item -LiteralPath $junction -Force
  }
  if (Test-Path -LiteralPath $root) {
    Remove-Item -LiteralPath $root -Recurse -Force
  }
  if (Test-Path -LiteralPath $repoFixture) {
    Remove-Item -LiteralPath $repoFixture -Force
  }
  Remove-Item Env:GM_BOUNDARY_ROOT,Env:GM_BOUNDARY_SIDECAR,Env:GM_BOUNDARY_FIXTURE,Env:GROWTHMAP_MAINTENANCE_DESTINATION -ErrorAction SilentlyContinue
}
