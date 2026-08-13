param([Parameter(Mandatory)][string]$ExpectedPin,[Parameter(Mandatory)][string]$SourceSha)
$ErrorActionPreference='Stop'
$resources='desktop/dist/win-unpacked/resources';$asar=Join-Path $resources 'app.asar';$config=Join-Path $resources 'commercial-config.json';$key=Join-Path $resources 'commercial/license_public_key.pem';$sidecar=Join-Path $resources 'sidecar/growthmap-sidecar.exe';$exe='desktop/dist/win-unpacked/GrowthMap.exe'
foreach($path in @($asar,$config,$key,$sidecar,$exe)){if(-not(Test-Path $path -PathType Leaf)){throw "Missing production package file: $path"}}
$doc=Get-Content $config -Raw|ConvertFrom-Json
if($doc.publisherStatus -cne 'COMMERCIAL_UNSIGNED' -or $doc.publisher -cne '月影塵（nerv00kaworu）'){throw 'Unsigned commercial publisher metadata mismatch'}
if($doc.activationApiOrigin -cne 'https://payments.growthmap.work' -or $doc.purchasePortalOrigin -cne 'https://whop.com' -or $doc.purchasePortalUrl -cne 'https://whop.com/growthmap/growthmap/'){throw 'Production activation or purchase authority mismatch'}
if($doc.updateUrl -cne '' -or $doc.updateOrigin -cne ''){throw 'Updater must be disabled in unsigned production v1'}
if($doc.licensePublicKeySha256 -cne $ExpectedPin -or (Get-FileHash $key -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedPin){throw 'Packaged G1 public-key pin mismatch'}
$pem=Get-Content $key -Raw;if($pem -notmatch 'BEGIN PUBLIC KEY' -or $pem -match 'PRIVATE KEY'){throw 'Packaged key is not public-only PEM'}
$extract=Join-Path $env:RUNNER_TEMP 'growthmap-production-asar-verify';if(Test-Path $extract){Remove-Item $extract -Recurse -Force};& npx --yes @electron/asar extract $asar $extract
$productRoots=@(Get-ChildItem $extract -Recurse -File -Filter 'package.json'|ForEach-Object{try{$metadata=Get-Content $_.FullName -Raw|ConvertFrom-Json;if($metadata.name -ceq 'growthmap-desktop' -and $metadata.main -ceq 'main.js'){$_.Directory.FullName}}catch{}})
if($productRoots.Count -ne 1){throw 'Unique GrowthMap desktop application root absent from ASAR'}
$appRoot=$productRoots[0];$main=Join-Path $appRoot 'main.js';$releaseMode=Join-Path $appRoot 'release-mode.json'
if(-not(Test-Path $main -PathType Leaf) -or -not(Test-Path $releaseMode -PathType Leaf)){throw 'Real main or release metadata absent from ASAR'}
$relativeFiles=Get-ChildItem $appRoot -Recurse -File|ForEach-Object{[IO.Path]::GetRelativePath($appRoot,$_.FullName)}
foreach($needle in @('e2e-main.js','e2e-commercial-config.js','create-e2e-fixture')){if($relativeFiles -contains $needle -or ($relativeFiles|Where-Object{$_ -like "*$needle*"})){throw "Forbidden ASAR material: $needle"}}
$sourceText=(Get-Content $main -Raw)
if($sourceText -match 'PRIVATE KEY'){throw 'Forbidden ASAR material: PRIVATE KEY'}
$mode=Get-Content $releaseMode -Raw|ConvertFrom-Json;if($mode.mode -cne 'unsigned-commercial' -or $mode.updatesEnabled -ne $false -or $mode.publisherDisplay -cne 'Unknown Publisher — 月影塵（nerv00kaworu）'){throw 'Unsigned commercial release metadata mismatch'}
$installer=Get-ChildItem desktop/dist -Filter 'GrowthMap-Setup-*.exe'|Select-Object -First 1;if(-not $installer){throw 'Installer absent'}
if((Get-AuthenticodeSignature $installer.FullName).Status -eq 'Valid'){throw 'No fake signing: candidate must remain unsigned'}
$installerHash=(Get-FileHash $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant();"$installerHash  $($installer.Name)"|Set-Content "$($installer.FullName).sha256" -Encoding ascii
$manifest=[ordered]@{schema_version=1;product='GrowthMap Windows Production Personal v1';source_sha=$SourceSha;unsigned=$true;publisher='月影塵（nerv00kaworu）';publisher_display='Unknown Publisher';activation_api_origin='https://payments.growthmap.work';activation_challenge_url='https://payments.growthmap.work/v1/activation/challenge';activation_complete_url='https://payments.growthmap.work/v1/activation/complete';purchase_portal_url='https://whop.com/growthmap/growthmap/';updates_enabled=$false;g1_public_key_sha256=$ExpectedPin;installer=$installer.Name;installer_sha256=$installerHash;asar_sha256=(Get-FileHash $asar -Algorithm SHA256).Hash.ToLowerInvariant();sidecar_sha256=(Get-FileHash $sidecar -Algorithm SHA256).Hash.ToLowerInvariant()}
$manifest|ConvertTo-Json|Set-Content desktop/dist/growthmap-windows-production-personal-v1-manifest.json -Encoding utf8
(Get-FileHash desktop/dist/growthmap-windows-production-personal-v1-manifest.json -Algorithm SHA256).Hash.ToLowerInvariant()+"  growthmap-windows-production-personal-v1-manifest.json"|Set-Content desktop/dist/growthmap-windows-production-personal-v1-manifest.json.sha256 -Encoding ascii
