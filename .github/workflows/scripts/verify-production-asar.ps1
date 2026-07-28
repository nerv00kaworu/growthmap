param([switch]$SelfTestOnly)

$ErrorActionPreference = 'Stop'

$requiredEntries = @('main.js','updater.js','update-recovery.js','managed-backup.js','commercial-config.js','commercial-config.json')
$forbiddenEntries = @('e2e-main.js', 'e2e-commercial-config.js', 'e2e-license-public-key.pem', 'E2E_ONLY', 'create-e2e-fixture', 'test-windows-', 'recovery-matrix')

function ConvertTo-NormalizedAsarEntry {
  param([Parameter(Mandatory)][string]$Entry)
  return (($Entry -replace '^[\\/]+', '') -replace '\\', '/')
}

function Assert-ProductionAsarEntries {
  param([Parameter(Mandatory)][string[]]$Entries)

  foreach ($needle in $forbiddenEntries) {
    if ($Entries | Select-String -SimpleMatch $needle) {
      throw "Production ASAR contains forbidden E2E/test entry: $needle"
    }
  }
  foreach ($entry in $Entries) {
    $normalizedEntry = ConvertTo-NormalizedAsarEntry $entry
    if ($normalizedEntry -match '(^|/)(tests?|test[-_]?helpers?)(/|$)') {
      throw "Production ASAR contains a test path: $entry"
    }
  }
  foreach ($requiredEntry in $requiredEntries) {
    if (-not ($Entries | Where-Object { (ConvertTo-NormalizedAsarEntry $_) -ceq $requiredEntry })) {
      throw "Production ASAR is missing required trust-boundary module: $requiredEntry"
    }
  }
}

function Invoke-AsarEntryContractSelfTest {
  $validEntries = @(
    '\main.js',
    '/updater.js',
    '\\update-recovery.js',
    '/managed-backup.js',
    '\commercial-config.js',
    '//commercial-config.json'
  )
  Assert-ProductionAsarEntries $validEntries

  $malformedEntries = @($validEntries | Where-Object { $_ -notmatch 'updater\.js$' }) + @('/nested/updater.js')
  try {
    Assert-ProductionAsarEntries $malformedEntries
    throw 'ASAR verifier self-test accepted a nested required updater module'
  } catch {
    if ($_.Exception.Message -notmatch 'missing required trust-boundary module: updater\.js') { throw }
  }

  try {
    Assert-ProductionAsarEntries ($validEntries + @('\\fixtures\\e2e-main.js'))
    throw 'ASAR verifier self-test accepted forbidden E2E material'
  } catch {
    if ($_.Exception.Message -notmatch 'forbidden E2E/test entry: e2e-main\.js') { throw }
  }
}

Invoke-AsarEntryContractSelfTest
if ($SelfTestOnly) {
  Write-Host 'Production ASAR entry contract self-test passed.'
  return
}

$dist = (Resolve-Path 'desktop/dist').Path
$asar = Join-Path $dist 'win-unpacked/resources/app.asar'
if (-not (Test-Path $asar -PathType Leaf)) { throw 'Final production app.asar is missing' }
if (-not (Get-ChildItem $dist -Filter 'GrowthMap-Setup-*.exe' | Select-Object -First 1)) {
  throw 'Final production installer is missing; refusing to inspect a stale unpacked dist'
}

$list = @(npx --yes asar list $asar)
if ($LASTEXITCODE -ne 0) { throw 'asar list failed' }
Assert-ProductionAsarEntries $list

$tmp = Join-Path $env:RUNNER_TEMP ("growthmap-production-asar-{0}" -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
# Extract only the two production metadata/code files that this gate reads.
Push-Location $tmp
try {
  npx --yes asar extract-file $asar main.js
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged main.js' }
  npx --yes asar extract-file $asar package.json
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged package.json' }
  npx --yes asar extract-file $asar commercial-config.json
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged commercial-config.json' }
} finally {
  Pop-Location
}

$mainPath = Join-Path $tmp 'main.js'
$packagePath = Join-Path $tmp 'package.json'
$commercialPath = Join-Path $tmp 'commercial-config.json'
if (-not (Test-Path $mainPath) -or -not (Test-Path $packagePath) -or -not (Test-Path $commercialPath)) {
  throw 'ASAR extract-file did not produce main.js, package.json and commercial-config.json'
}
$main = Get-Content $mainPath -Raw
$packageText = Get-Content $packagePath -Raw
foreach ($needle in @('GROWTHMAP_DESKTOP_E2E', 'E2E_IMPORT', 'E2E_ONLY', 'remote-debugging-port', 'e2e-main')) {
  if ($main.Contains($needle) -or $packageText.Contains($needle)) {
    throw "Production ASAR contains forbidden E2E marker: $needle"
  }
}
$package = $packageText | ConvertFrom-Json
if ($package.main -ne 'main.js') { throw "Production package main must be main.js, got '$($package.main)'" }
$commercialText = Get-Content $commercialPath -Raw
$commercial = $commercialText | ConvertFrom-Json
$expectedCommercial = @('schemaVersion','productMajor','licensePublicKeyResource','licensePublicKeySha256','checkoutOrigin','checkoutUrl','updateUrl','updateOrigin','publisher','publisherStatus') | Sort-Object
$actualCommercial = @($commercial.psobject.Properties.Name) | Sort-Object
if (Compare-Object $expectedCommercial $actualCommercial) { throw 'Commercial config schema mismatch' }
if ($env:GROWTHMAP_COMMERCIAL_RELEASE -eq '1' -and ($commercialText -match 'REPLACE|EXAMPLE|TBD|UNAPPROVED')) { throw 'Commercial ASAR contains placeholder trust configuration' }

Write-Host "Production ASAR verified from final installer dist: $asar"
