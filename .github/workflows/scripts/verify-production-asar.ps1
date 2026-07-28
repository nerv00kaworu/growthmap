param([switch]$SelfTestOnly)

$ErrorActionPreference = 'Stop'

$fixturePath = Join-Path $PSScriptRoot 'fixtures/production-package-layout.json'
$layout = Get-Content $fixturePath -Raw | ConvertFrom-Json
$requiredAsarEntries = @($layout.requiredAsarEntries)
$requiredResourceEntries = @($layout.requiredResourceEntries)
$forbiddenEntries = @('e2e-main.js', 'e2e-commercial-config.js', 'e2e-license-public-key.pem', 'E2E_ONLY', 'create-e2e-fixture', 'e2e-config-support', 'renderer-e2e', 'test-windows-', 'recovery-matrix')

function ConvertTo-NormalizedPackageEntry {
  param([Parameter(Mandatory)][string]$Entry)
  # @electron/asar emits root entries with a leading slash on Windows too. Trim
  # captured CRLF/whitespace, canonicalize separators, then remove all roots.
  return ((($Entry.Trim()) -replace '\\', '/') -replace '^/+', '')
}

function Assert-NoProductionTestEntries {
  param(
    [Parameter(Mandatory)][string[]]$Entries,
    [Parameter(Mandatory)][string]$Location
  )
  foreach ($entry in $Entries) {
    $normalized = ConvertTo-NormalizedPackageEntry $entry
    foreach ($needle in $forbiddenEntries) {
      if ($normalized.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production $Location contains forbidden E2E/test entry: $normalized"
      }
    }
    if ($normalized -match '(?i)(^|/|[-_])e2e([/_-]|$)' -or $normalized -match '(?i)(^|/)(tests?|test[-_]?helpers?)(/|$)') {
      throw "Production $Location contains a test path: $normalized"
    }
  }
}

function Assert-RequiredEntries {
  param(
    [Parameter(Mandatory)][string[]]$Entries,
    [Parameter(Mandatory)][string[]]$Required,
    [Parameter(Mandatory)][string]$Location
  )
  $normalized = @($Entries | ForEach-Object { ConvertTo-NormalizedPackageEntry $_ })
  foreach ($requiredEntry in $Required) {
    # Archive/resource manifests use canonical casing even though Windows file
    # lookup is normally insensitive. Exact ordinal equality catches drift.
    if (-not ($normalized | Where-Object { $_ -ceq $requiredEntry })) {
      $name = [IO.Path]::GetFileName($requiredEntry)
      $nearby = @($normalized | Where-Object { $_.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0 } | Select-Object -First 20)
      if (-not $nearby.Count) {
        $nearby = @($normalized | Where-Object { $_ -notmatch '/' -or $_ -match '(?i)(commercial|identity|update|backup|startup)' } | Select-Object -First 40)
      }
      $detail = if ($nearby.Count) { $nearby -join "`n  " } else { '<empty manifest>' }
      throw "Production $Location is missing required trust-boundary entry: $requiredEntry`nNormalized entries near '$name' (or relevant roots):`n  $detail"
    }
  }
}

function Assert-ProductionPackageLayout {
  param(
    [Parameter(Mandatory)][string[]]$AsarEntries,
    [Parameter(Mandatory)][string[]]$ResourceEntries
  )
  Assert-NoProductionTestEntries $AsarEntries 'ASAR'
  Assert-NoProductionTestEntries $ResourceEntries 'resources'
  Assert-RequiredEntries $AsarEntries $requiredAsarEntries 'ASAR'
  Assert-RequiredEntries $ResourceEntries $requiredResourceEntries 'resources'
}

function Invoke-ProductionPackageLayoutSelfTest {
  $asarFixture = @($layout.asarListLines)
  $resourceFixture = @($layout.requiredResourceEntries | ForEach-Object { "\\$_`r" })
  Assert-ProductionPackageLayout $asarFixture $resourceFixture

  $missing = @($asarFixture | Where-Object { (ConvertTo-NormalizedPackageEntry $_) -cne 'updater.js' }) + @('/nested/updater.js')
  try {
    Assert-ProductionPackageLayout $missing $resourceFixture
    throw 'Package verifier self-test accepted a nested required updater module'
  } catch {
    if ($_.Exception.Message -notmatch 'missing required trust-boundary entry: updater\.js') { throw }
  }

  foreach ($case in @(
    @{ Asar = @($asarFixture + '\fixtures\E2E-MAIN.js'); Resources = $resourceFixture; Expected = 'Production ASAR contains forbidden' },
    @{ Asar = $asarFixture; Resources = @($resourceFixture + '\commercial\e2e-license-public-key.pem'); Expected = 'Production resources contains forbidden' }
  )) {
    try {
      Assert-ProductionPackageLayout $case.Asar $case.Resources
      throw 'Package verifier self-test accepted forbidden E2E material'
    } catch {
      if (-not $_.Exception.Message.StartsWith($case.Expected, [StringComparison]::Ordinal)) { throw }
    }
  }
}

Invoke-ProductionPackageLayoutSelfTest
if ($SelfTestOnly) {
  Write-Host 'Production package layout fixture self-test passed.'
  return
}

$dist = (Resolve-Path 'desktop/dist').Path
$resources = Join-Path $dist 'win-unpacked/resources'
$asar = Join-Path $resources 'app.asar'
if (-not (Test-Path $asar -PathType Leaf)) { throw 'Final production app.asar is missing' }
if (-not (Get-ChildItem $dist -Filter 'GrowthMap-Setup-*.exe' | Select-Object -First 1)) {
  throw 'Final production installer is missing; refusing to inspect a stale unpacked dist'
}

# Use the maintained package explicitly; its output is one path per line and may
# contain leading separators/CRLF depending on capture and platform.
$list = @(npx --yes '@electron/asar' list $asar)
if ($LASTEXITCODE -ne 0) { throw '@electron/asar list failed' }
$resourceList = @(Get-ChildItem $resources -File -Recurse | ForEach-Object {
  [IO.Path]::GetRelativePath($resources, $_.FullName)
})
Assert-ProductionPackageLayout $list $resourceList

$tmp = Join-Path $env:RUNNER_TEMP ("growthmap-production-asar-{0}" -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
Push-Location $tmp
try {
  npx --yes '@electron/asar' extract-file $asar main.js
  if ($LASTEXITCODE -ne 0) { throw 'Could not extract packaged main.js' }
  npx --yes '@electron/asar' extract-file $asar package.json
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
foreach ($needle in @('GROWTHMAP_DESKTOP_E2E', 'E2E_IMPORT', 'E2E_ONLY', 'remote-debugging-port', 'e2e-main')) {
  if ($main.Contains($needle) -or $packageText.Contains($needle)) {
    throw "Production ASAR contains forbidden E2E marker: $needle"
  }
}
$package = $packageText | ConvertFrom-Json
if ($package.main -cne 'main.js') { throw "Production package main must be main.js, got '$($package.main)'" }

# commercial-config.json is intentionally an extraResource because packaged
# runtime loads it from process.resourcesPath. Verify that exact resource,
# rather than falsely requiring/extracting an ASAR copy.
$commercialPath = Join-Path $resources 'commercial-config.json'
$sourceCommercialPath = (Resolve-Path 'desktop/commercial-config.json').Path
if ((Get-FileHash $commercialPath -Algorithm SHA256).Hash -cne (Get-FileHash $sourceCommercialPath -Algorithm SHA256).Hash) {
  throw 'Packaged commercial-config.json hash differs from the production source resource'
}
$commercialText = Get-Content $commercialPath -Raw
$commercial = $commercialText | ConvertFrom-Json
$expectedCommercial = @('schemaVersion','productMajor','licensePublicKeyResource','licensePublicKeySha256','checkoutOrigin','checkoutUrl','updateUrl','updateOrigin','publisher','publisherStatus') | Sort-Object
$actualCommercial = @($commercial.psobject.Properties.Name) | Sort-Object
if (Compare-Object $expectedCommercial $actualCommercial) { throw 'Commercial config schema mismatch' }
if ($env:GROWTHMAP_COMMERCIAL_RELEASE -eq '1' -and ($commercialText -match 'REPLACE|EXAMPLE|TBD|UNAPPROVED')) { throw 'Commercial resource contains placeholder trust configuration' }

Write-Host "Production ASAR and resources verified from final installer dist: $asar"
