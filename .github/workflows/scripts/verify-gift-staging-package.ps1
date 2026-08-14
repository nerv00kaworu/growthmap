param([Parameter(Mandatory)][string]$ExpectedOrigin,[Parameter(Mandatory)][string]$ExpectedPin,[Parameter(Mandatory)][string]$SourceSha)
$ErrorActionPreference='Stop'
$resources='desktop/dist/win-unpacked/resources';$asar=Join-Path $resources 'app.asar';$config=Join-Path $resources 'commercial-config.json';$key=Join-Path $resources 'commercial/license_public_key.pem';$mcp=Join-Path $resources 'growthmap-mcp.exe'
foreach($path in @($asar,$config,$key,$mcp,'desktop/dist/win-unpacked/GrowthMap.exe')){if(-not(Test-Path $path -PathType Leaf)){throw "Missing staged package file: $path"}}
$doc=Get-Content $config -Raw|ConvertFrom-Json
if($doc.publisherStatus -cne 'STAGING_ONLY' -or $doc.activationApiOrigin -cne $ExpectedOrigin -or $doc.licensePublicKeySha256 -cne $ExpectedPin){throw 'Staging public config mismatch'}
if((Get-FileHash $key -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedPin){throw 'Packaged key pin mismatch'}
$list=& npx --yes @electron/asar list $asar
foreach($needle in @('e2e-main.js','e2e-commercial-config.js','gift_api.py','authority.py','PRIVATE KEY','create-e2e-fixture')){if(($list -join "`n") -match [regex]::Escape($needle)){throw "Forbidden ASAR entry: $needle"}}
if(($list -join "`n") -notmatch 'release-mode.json'){throw 'Staging release mode metadata absent'}
$installer=Get-ChildItem desktop/dist -Filter 'GrowthMap-Setup-*.exe'|Select-Object -First 1;if(-not $installer){throw 'Installer absent'}
$sig=Get-AuthenticodeSignature $installer.FullName;if($sig.Status -eq 'Valid'){throw 'Staging candidate must remain explicitly unsigned'}
$hash=(Get-FileHash $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant();"$hash  $($installer.Name)"|Set-Content "$($installer.FullName).sha256" -Encoding ascii
$manifest=[ordered]@{schema_version=1;source_sha=$SourceSha;unsigned=$true;publisher_display='Unknown Publisher (STAGING ONLY)';authority_origin=$ExpectedOrigin;public_key_sha256=$ExpectedPin;installer=$installer.Name;installer_sha256=$hash;asar_sha256=(Get-FileHash $asar -Algorithm SHA256).Hash.ToLowerInvariant();sidecar_sha256=(Get-FileHash 'desktop/dist/win-unpacked/resources/sidecar/growthmap-sidecar.exe' -Algorithm SHA256).Hash.ToLowerInvariant();mcp_sha256=(Get-FileHash $mcp -Algorithm SHA256).Hash.ToLowerInvariant()}
$manifest|ConvertTo-Json|Set-Content desktop/dist/gift-staging-artifact-manifest.json -Encoding utf8
