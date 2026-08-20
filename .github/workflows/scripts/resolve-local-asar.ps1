$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$nodeModulesRoot = (Resolve-Path (Join-Path $repo 'desktop/node_modules')).Path
$expectedPackageRoot = (Resolve-Path (Join-Path $nodeModulesRoot '@electron/asar')).Path
$lockPath = Join-Path $repo 'desktop/package-lock.json'
$packagePath = Join-Path $expectedPackageRoot 'package.json'
foreach ($path in @($lockPath, $packagePath)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Repository-local ASAR dependency is unavailable: $path" }
}
$packageRoot = (Resolve-Path (Split-Path $packagePath)).Path
if ($packageRoot -cne $expectedPackageRoot -or -not $packageRoot.StartsWith($nodeModulesRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'ASAR package root is not the exact expected package under desktop/node_modules'
}
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$installed = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
$locked = $lock.packages.'node_modules/@electron/asar'
$declaredVersion = $lock.packages.''.devDependencies.'@electron/asar'
$lockedVersion = $locked.version
if ($declaredVersion -cne '4.0.1' -or $lockedVersion -cne $declaredVersion -or $installed.version -cne $lockedVersion) {
  throw "Repository-local ASAR version mismatch (declared=$declaredVersion locked=$lockedVersion installed=$($installed.version))"
}
$rawBin = [string]$installed.bin.asar
if ([IO.Path]::IsPathFullyQualified($rawBin) -or $rawBin -match '(^|[\\/])\.\.([\\/]|$)') { throw 'ASAR executable path must be package-relative without traversal' }
$normalizedBin = $rawBin -replace '\\','/'
if ($normalizedBin.StartsWith('./')) { $normalizedBin = $normalizedBin.Substring(2) }
if ($normalizedBin -cne 'bin/asar.mjs' -or [string]::IsNullOrWhiteSpace($locked.integrity)) { throw 'Locked ASAR executable metadata is absent or unexpected' }
$entry = (Resolve-Path (Join-Path $packageRoot $normalizedBin)).Path
if (-not $entry.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'ASAR entry escapes its locked package root' }
# CI uses an ephemeral npm-ci tree; execute this resolved package entry directly so
# no mutable PATH shim or registry lookup occurs between validation and invocation.
Write-Output $entry
