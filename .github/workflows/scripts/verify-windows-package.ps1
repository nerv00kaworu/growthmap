$ErrorActionPreference = 'Stop'

$resources = 'desktop/dist/win-unpacked/resources'
$sidecar = Join-Path $resources 'sidecar/growthmap-sidecar.exe'
$mcp = Join-Path $resources 'growthmap-mcp.exe'
$frontend = Join-Path $resources 'frontend'
$required = @(
  $sidecar,
  $mcp,
  (Join-Path $frontend 'index.html'),
  (Join-Path $resources 'legal/LICENSE'),
  (Join-Path $resources 'legal/EULA.md'),
  (Join-Path $resources 'legal/PRIVACY.md'),
  (Join-Path $resources 'legal/THIRD_PARTY_NOTICES.md'),
  (Join-Path $resources 'commercial-config.json')
)
foreach ($item in $required) {
  if (-not (Test-Path $item -PathType Leaf)) { throw "Missing packaged resource: $item" }
}
$config = Get-Content (Join-Path $resources 'commercial-config.json') -Raw | ConvertFrom-Json
$keyPath = Join-Path $resources $config.licensePublicKeyResource
if (-not (Test-Path $keyPath -PathType Leaf)) { throw "Configured license public key missing: $keyPath" }
$keyHash = (Get-FileHash $keyPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($config.licensePublicKeySha256 -ne $keyHash) { throw 'Packaged license public key hash mismatch' }
if ($env:GROWTHMAP_COMMERCIAL_RELEASE -eq '1' -and $config.publisherStatus -ne 'APPROVED') { throw 'Packaged commercial trust config mismatch' }
if ($env:GROWTHMAP_COMMERCIAL_RELEASE -ne '1') {
  if ($config.publisherStatus -ne 'NONCOMMERCIAL_UNSIGNED') { throw 'Unsigned package is not explicitly noncommercial' }
  foreach ($field in @('activationApiOrigin','purchasePortalOrigin','purchasePortalUrl','updateUrl','updateOrigin')) {
    if ($config.$field -ne '') { throw "Unsigned package unexpectedly enables online authority: $field" }
  }
}

$port = Get-Random -Minimum 20000 -Maximum 50000
$token = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$verdictJson = node -e @'
const crypto=require('node:crypto');
const {createStartupVerdict,startupVerdictEnv}=require('./desktop/startup-verdict');
const {publicKey,privateKey}=crypto.generateKeyPairSync('ed25519');
const devicePublicKey=publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64');
const privateKeyPem=privateKey.export({format:'pem',type:'pkcs8'});
const token=process.argv[1];
const verdict=createStartupVerdict({mode:'fresh',token,devicePublicKey,privateKeyPem});
process.stdout.write(JSON.stringify(startupVerdictEnv({verdict,token})));
'@ $token
if ($LASTEXITCODE -ne 0 -or -not $verdictJson) { throw 'Could not create authenticated packaged sidecar smoke verdict' }
$verdictEnv = $verdictJson | ConvertFrom-Json
$tmp = Join-Path $env:RUNNER_TEMP 'growthmap-sidecar-smoke'
New-Item $tmp -ItemType Directory -Force | Out-Null
$dbPath = (Join-Path $tmp 'smoke.db').Replace('\', '/')
$stdout = Join-Path $tmp 'sidecar.stdout.log'
$stderr = Join-Path $tmp 'sidecar.stderr.log'
Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue

$env:GROWTHMAP_DESKTOP_MODE = '1'
$env:GROWTHMAP_FRESH_INSTALL = '1'
foreach ($entry in $verdictEnv.PSObject.Properties) {
  [Environment]::SetEnvironmentVariable($entry.Name, [string]$entry.Value, 'Process')
}
$env:GROWTHMAP_PORT = "$port"
$env:DATABASE_URL = "sqlite+aiosqlite:///$dbPath"
$env:GROWTHMAP_LICENSE_FILE = Join-Path $tmp 'license.json'
$env:GROWTHMAP_STATIC_DIR = (Resolve-Path $frontend).Path

$process = Start-Process $sidecar -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
  $deadline = [DateTime]::UtcNow.AddSeconds(90)
  $ok = $false
  while ([DateTime]::UtcNow -lt $deadline -and -not $ok) {
    if ($process.HasExited) {
      $err = if (Test-Path $stderr) { Get-Content $stderr -Raw } else { '' }
      $out = if (Test-Path $stdout) { Get-Content $stdout -Raw } else { '' }
      throw "Packaged sidecar exited before readiness (code $($process.ExitCode)). stdout=$out stderr=$err"
    }
    try {
      $response = Invoke-WebRequest "http://127.0.0.1:$port/api/health/deep" `
        -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -eq 200) { $ok = $true }
    }
    catch { Start-Sleep -Milliseconds 250 }
  }
  if (-not $ok) {
    $err = if (Test-Path $stderr) { Get-Content $stderr -Raw } else { '' }
    $out = if (Test-Path $stdout) { Get-Content $stdout -Raw } else { '' }
    throw "Packaged sidecar authenticated health smoke timed out. stdout=$out stderr=$err"
  }

  $unauthenticated = Invoke-WebRequest "http://127.0.0.1:$port/api/health/deep" `
    -UseBasicParsing -TimeoutSec 2 -SkipHttpErrorCheck
  if ($unauthenticated.StatusCode -ne 401) {
    throw "Unauthenticated health expected 401, got $($unauthenticated.StatusCode)"
  }
  Write-Host 'Windows unpacked resource and authenticated sidecar smoke passed.'
}
finally {
  if (-not $process.HasExited) { Stop-Process $process -Force -ErrorAction SilentlyContinue }
  try { $process.WaitForExit(10000) | Out-Null } catch {}
  $process.Dispose()
}
