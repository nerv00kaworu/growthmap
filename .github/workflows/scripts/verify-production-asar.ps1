$ErrorActionPreference = 'Stop'

$dist = (Resolve-Path 'desktop/dist').Path
$asar = Join-Path $dist 'win-unpacked/resources/app.asar'
if (-not (Test-Path $asar -PathType Leaf)) { throw 'Final production app.asar is missing' }
if (-not (Get-ChildItem $dist -Filter 'GrowthMap-Setup-*.exe' | Select-Object -First 1)) {
  throw 'Final production installer is missing; refusing to inspect a stale unpacked dist'
}

$list = @(npx --yes asar list $asar)
if ($LASTEXITCODE -ne 0) { throw 'asar list failed' }
$forbiddenEntries = @('e2e-main.js', 'create-e2e-fixture', 'test-windows-', 'recovery-matrix')
foreach ($needle in $forbiddenEntries) {
  if ($list | Select-String -SimpleMatch $needle) {
    throw "Production ASAR contains forbidden E2E/test entry: $needle"
  }
}
foreach ($entry in $list) {
  if ($entry -match '(^|[\\/])(tests?|test[-_]?helpers?)([\\/]|$)') {
    throw "Production ASAR contains a test path: $entry"
  }
}

$tmp = Join-Path $env:RUNNER_TEMP ("growthmap-production-asar-{0}" -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
# Extract only the two production metadata/code files that this gate reads.
Push-Location $tmp
try {
  npx --yes asar extract-file $asar main.js
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged main.js' }
  npx --yes asar extract-file $asar package.json
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged package.json' }
} finally {
  Pop-Location
}

$mainPath = Join-Path $tmp 'main.js'
$packagePath = Join-Path $tmp 'package.json'
if (-not (Test-Path $mainPath) -or -not (Test-Path $packagePath)) {
  throw 'ASAR extract-file did not produce main.js and package.json'
}
$main = Get-Content $mainPath -Raw
$packageText = Get-Content $packagePath -Raw
foreach ($needle in @('GROWTHMAP_DESKTOP_E2E', 'E2E_IMPORT', 'remote-debugging-port', 'e2e-main')) {
  if ($main.Contains($needle) -or $packageText.Contains($needle)) {
    throw "Production ASAR contains forbidden E2E marker: $needle"
  }
}
$package = $packageText | ConvertFrom-Json
if ($package.main -ne 'main.js') { throw "Production package main must be main.js, got '$($package.main)'" }

Write-Host "Production ASAR verified from final installer dist: $asar"
