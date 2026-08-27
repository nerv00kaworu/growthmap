param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedManifestSha256,[Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedSourceSha,[Parameter(Mandatory)][string]$TrustedNodePath,[Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedTrustedNodeSha256,[Parameter(Mandatory)][ValidatePattern('^v22\.[0-9]+\.[0-9]+$')][string]$ExpectedTrustedNodeVersion)
$ErrorActionPreference = 'Stop'
$runtimeVersion=[Version]$PSVersionTable.PSVersion.ToString()
if ($PSVersionTable.PSEdition -cne 'Core' -or $runtimeVersion -lt [Version]'7.4.0') { throw 'Production installed acceptance requires PowerShell Core 7.4 or newer' }
$diag = Join-Path $env:RUNNER_TEMP 'growthmap-installed-acceptance.json'; $id = [guid]::NewGuid().ToString('N')
$install = Join-Path $env:LOCALAPPDATA "Programs\GrowthMap-R39-$id"; $profile = Join-Path $env:RUNNER_TEMP "growthmap-installed-profile-$id"
$stage = Join-Path $env:RUNNER_TEMP "growthmap-installer-stage-$id"; $externalOwner = Join-Path $env:RUNNER_TEMP "growthmap-installed-owner-$id.json"
$cleanupErrors = [Collections.Generic.List[string]]::new(); $installerStarted = $false
function RegistryRecords {
 $records = [Collections.Generic.List[object]]::new()
 foreach ($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser,[Microsoft.Win32.RegistryHive]::LocalMachine)) {
  foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64)) {
   $base = $null; $root = $null
   try {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive,$view)
    $root = $base.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall',$false)
    if ($null -eq $root) { continue }
    foreach ($subkey in @($root.GetSubKeyNames() | Sort-Object)) {
     $key = $null
     try {
      $key = $root.OpenSubKey($subkey,$false); if ($null -eq $key) { continue }
      $name = [string]$key.GetValue('DisplayName','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $publisher = [string]$key.GetValue('Publisher','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $location = [string]$key.GetValue('InstallLocation','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $uninstall = [string]$key.GetValue('UninstallString','',[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $identity = "$subkey $name $publisher $location $uninstall"
      if ($identity -match '(?i)GrowthMap|com\.growthmap\.desktop') {
       $records.Add([ordered]@{hive=$hive.ToString();view=$view.ToString();subkey=$subkey.Substring(0,[Math]::Min(256,$subkey.Length));name=$name.Substring(0,[Math]::Min(256,$name.Length));publisher=$publisher.Substring(0,[Math]::Min(256,$publisher.Length));location=$location.Substring(0,[Math]::Min(1024,$location.Length));uninstall=$uninstall.Substring(0,[Math]::Min(1024,$uninstall.Length))})
      }
     } finally { if ($null -ne $key) { $key.Dispose() } }
    }
   } finally { if ($null -ne $root) { $root.Dispose() }; if ($null -ne $base) { $base.Dispose() } }
  }
 }
 @($records | Sort-Object hive,view,subkey)
}
function Footprint {
 $records = @(RegistryRecords)
 $paths = @((Join-Path $env:LOCALAPPDATA 'Programs\GrowthMap'),(Join-Path $env:ProgramFiles 'GrowthMap'),(Join-Path ${env:ProgramFiles(x86)} 'GrowthMap')) | Where-Object { $_ -and (Test-Path $_) }
 $shortcuts = @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'GrowthMap.lnk'),(Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'GrowthMap.lnk'),(Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\GrowthMap.lnk'),(Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\GrowthMap.lnk')) | Where-Object { Test-Path $_ }
 $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -ieq 'GrowthMap.exe' } | ForEach-Object { [ordered]@{ pid=$_.ProcessId; created=$_.CreationDate; path=$_.ExecutablePath } })
 [ordered]@{ records=$records; paths=@($paths|Sort-Object); shortcuts=@($shortcuts|Sort-Object); processes=@($processes) }
}
function Canonical($value) { $value | ConvertTo-Json -Depth 8 -Compress }
function Assert-Owned { if (-not (Test-Path $externalOwner -PathType Leaf)) { throw 'external ownership marker absent' }; $owner=Get-Content $externalOwner -Raw|ConvertFrom-Json; if ($owner.id -cne $id -or $owner.install -cne $install -or $owner.profile -cne $profile -or $owner.stage -cne $stage) { throw 'external ownership marker mismatch' } }
function Assert-NoReparseAncestors([string]$Path) {
 $cursor=[IO.Path]::GetFullPath($Path)
 while ($cursor) { if (Test-Path -LiteralPath $cursor) { $item=Get-Item -LiteralPath $cursor -Force; if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse path rejected: $cursor" } }; $parent=[IO.Directory]::GetParent($cursor); if ($null -eq $parent) { break }; $cursor=$parent.FullName }
}
if (-not ('GrowthMap.Acceptance.LockedLauncher' -as [type])) {
 Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
namespace GrowthMap.Acceptance {
 [StructLayout(LayoutKind.Sequential)] struct BY_HANDLE_FILE_INFORMATION { public uint FileAttributes; public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime, LastAccessTime, LastWriteTime; public uint VolumeSerialNumber, FileSizeHigh, FileSizeLow, NumberOfLinks, FileIndexHigh, FileIndexLow; }
 public static class LockedLauncher {
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(IntPtr h, out BY_HANDLE_FILE_INFORMATION i);
  static string Hex(byte[] b) { return BitConverter.ToString(b).Replace("-","").ToLowerInvariant(); }
  public static int VerifyAndRun(string file, string expectedHash, long expectedSize, string arguments) {
   string canonical=Path.GetFullPath(file); if (!String.Equals(canonical,file,StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("installer path is not canonical");
   using (var stream=new FileStream(canonical,FileMode.Open,FileAccess.Read,FileShare.Read)) {
    BY_HANDLE_FILE_INFORMATION before; if(!GetFileInformationByHandle(stream.SafeFileHandle.DangerousGetHandle(),out before)) throw new System.ComponentModel.Win32Exception();
    if(stream.Length!=expectedSize) throw new InvalidOperationException("staged installer size mismatch");
    string hash; using(var sha=SHA256.Create()) hash=Hex(sha.ComputeHash(stream)); if(!String.Equals(hash,expectedHash,StringComparison.Ordinal)) throw new InvalidOperationException("staged installer hash mismatch");
    stream.Position=0; BY_HANDLE_FILE_INFORMATION after; if(!GetFileInformationByHandle(stream.SafeFileHandle.DangerousGetHandle(),out after)) throw new System.ComponentModel.Win32Exception();
    if(before.VolumeSerialNumber!=after.VolumeSerialNumber || before.FileIndexHigh!=after.FileIndexHigh || before.FileIndexLow!=after.FileIndexLow || before.CreationTime.dwHighDateTime!=after.CreationTime.dwHighDateTime || before.CreationTime.dwLowDateTime!=after.CreationTime.dwLowDateTime) throw new InvalidOperationException("staged installer identity changed");
    var p=Process.Start(new ProcessStartInfo(canonical,arguments){UseShellExecute=false,CreateNoWindow=true}); if(p==null) throw new InvalidOperationException("installer did not start"); p.WaitForExit(); return p.ExitCode;
   }
  }
 }
}
'@
}
$before = Footprint
if ($before.records.Count -or $before.paths.Count -or $before.shortcuts.Count -or $before.processes.Count) { throw 'Preexisting GrowthMap footprint detected; isolated acceptance refuses to install' }
if ((Test-Path $install) -or (Test-Path $profile) -or (Test-Path $stage) -or (Test-Path $externalOwner)) { throw 'task destination, profile, staging directory, or marker preexists' }
@{schema=1;id=$id;install=$install;profile=$profile;stage=$stage;before=$before} | ConvertTo-Json -Depth 8 | Set-Content $externalOwner -Encoding utf8
try {
 $manifest=[IO.Path]::GetFullPath($ManifestPath); Assert-NoReparseAncestors $manifest
 if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw 'production manifest absent' }
 $manifestBytes=[IO.File]::ReadAllBytes($manifest); $sha=[Security.Cryptography.SHA256]::Create()
 try { $manifestHash=([BitConverter]::ToString($sha.ComputeHash($manifestBytes))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
 if ($manifestHash -cne $ExpectedManifestSha256) { throw 'production manifest differs from verifier-bound digest' }
 $m=[Text.Encoding]::UTF8.GetString($manifestBytes)|ConvertFrom-Json
 if ($m.schema_version -ne 1 -or $m.product -cne 'GrowthMap Windows Production Personal v1' -or $m.source_sha -cne $ExpectedSourceSha -or $m.unsigned -ne $true -or $m.installer -notmatch '^GrowthMap-Setup-[A-Za-z0-9._-]+\.exe$' -or [string]$m.installer_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'production manifest authority mismatch' }
 $all=@(Get-ChildItem desktop/dist -File -Filter 'GrowthMap-Setup-*.exe'); if ($all.Count -ne 1) { throw "Expected exactly one installer, found $($all.Count)" }; $source=$all[0]
 if ($source.Name -cne [string]$m.installer) { throw 'manifest installer filename mismatch' }
 $acl=New-Object Security.AccessControl.DirectorySecurity; $acl.SetAccessRuleProtection($true,$false); $inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'; $prop=[Security.AccessControl.PropagationFlags]::None
 foreach($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,(New-Object Security.Principal.SecurityIdentifier('S-1-5-18')),(New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))) { $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl',$inherit,$prop,'Allow'))) }
 foreach($ownedDirectory in @($stage,$profile)) { New-Item -ItemType Directory -Path $ownedDirectory | Out-Null; Set-Acl -LiteralPath $ownedDirectory -AclObject $acl; Assert-NoReparseAncestors $ownedDirectory }
 Set-Content (Join-Path $profile '.growthmap-ci-owned') 'growthmap-installed-acceptance-v1' -NoNewline -Encoding ascii
 $installer=[IO.Path]::GetFullPath((Join-Path $stage 'GrowthMap-Setup-verified.exe')); Copy-Item -LiteralPath $source.FullName -Destination $installer
 Assert-NoReparseAncestors $installer; $staged=Get-Item -LiteralPath $installer -Force; if (($staged.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'staged installer reparse target rejected' }
 if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -cne $m.installer_sha256) { throw 'staged installer changed after production verification' }
 Assert-Owned; Assert-NoReparseAncestors $installer
 if ($install.Contains('"')) { throw 'NSIS destination path contains a quote' }
 $installerStarted=$true
 $exit=[GrowthMap.Acceptance.LockedLauncher]::VerifyAndRun($installer,[string]$m.installer_sha256,[long]$staged.Length,"/S /D=$install"); if ($exit -ne 0) { throw "installer exit $exit" }
 if (-not (Test-Path $install -PathType Container)) { throw 'isolated install directory absent' }
 $exe=Join-Path $install 'GrowthMap.exe'; $resources=Join-Path $install 'resources'; foreach($p in @($exe,(Join-Path $resources 'app.asar'),(Join-Path $resources 'sidecar/growthmap-sidecar.exe'),(Join-Path $resources 'growthmap-mcp.exe'))) { if (-not (Test-Path $p -PathType Leaf)) { throw "installed production file absent: $p" } }
 foreach($pair in @(@($exe,$m.executable_sha256),@((Join-Path $resources 'app.asar'),$m.asar_sha256),@((Join-Path $resources 'sidecar/growthmap-sidecar.exe'),$m.sidecar_sha256),@((Join-Path $resources 'growthmap-mcp.exe'),$m.mcp_sha256))) { if ((Get-FileHash $pair[0] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $pair[1]) { throw "installed hash mismatch: $($pair[0])" } }
 $nodePath=[IO.Path]::GetFullPath($TrustedNodePath); $runnerTemp=[IO.Path]::GetFullPath($env:RUNNER_TEMP)
 if (-not $runnerTemp -or -not $nodePath.StartsWith($runnerTemp.TrimEnd('\')+'\growthmap-trusted-node-v22\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Preserved Node executable is outside the task-owned runner staging directory' }
 Assert-NoReparseAncestors $nodePath
 if (-not (Test-Path -LiteralPath $nodePath -PathType Leaf)) { throw 'Preserved trusted Node executable disappeared before acceptance' }
 $nodeSourceHash=(Get-FileHash -LiteralPath $nodePath -Algorithm SHA256).Hash.ToLowerInvariant()
 if ($nodeSourceHash -cne $ExpectedTrustedNodeSha256) { throw 'Preserved trusted Node digest mismatch' }
 $acceptNode=[IO.Path]::GetFullPath((Join-Path $stage 'node.exe')); Copy-Item -LiteralPath $nodePath -Destination $acceptNode
 Assert-NoReparseAncestors $acceptNode; $acceptNodeItem=Get-Item -LiteralPath $acceptNode -Force
 if (($acceptNodeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or (Get-FileHash -LiteralPath $acceptNode -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedTrustedNodeSha256) { throw 'Staged acceptance Node identity mismatch' }
 $systemPath=(Join-Path $env:SystemRoot 'System32')+';'+$env:SystemRoot
 $acceptEnv=@{GROWTHMAP_ACCEPTANCE_EXE=$exe;GROWTHMAP_ACCEPTANCE_PROFILE=$profile;GROWTHMAP_ACCEPTANCE_DIAGNOSTIC=$diag;PATH=$systemPath;SYSTEMROOT=$env:SYSTEMROOT;WINDIR=$env:WINDIR;TEMP=$env:TEMP;TMP=$env:TMP;LOCALAPPDATA=$env:LOCALAPPDATA;APPDATA=$env:APPDATA;USERPROFILE=$env:USERPROFILE}
 $stagedVersionProbe=Start-Process -FilePath $acceptNode -ArgumentList @('--version') -WorkingDirectory $stage -Environment $acceptEnv -Wait -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $stage 'node-version.txt')
 $stagedNodeVersion=(Get-Content (Join-Path $stage 'node-version.txt') -Raw).Trim()
 if ($stagedVersionProbe.ExitCode -ne 0 -or $stagedNodeVersion -cne $ExpectedTrustedNodeVersion) { throw 'Staged acceptance Node execution probe failed' }
 $accept=Start-Process -FilePath $acceptNode -ArgumentList @('.github/workflows/scripts/run-installed-production-acceptance.js') -WorkingDirectory (Get-Location).Path -Environment $acceptEnv -Wait -PassThru -NoNewWindow
 if ($accept.ExitCode -ne 0) { throw 'installed production credential-restart acceptance failed' }
} finally {
 try {
  if ($installerStarted) {
   Assert-Owned; $uninstaller=Join-Path $install 'Uninstall GrowthMap.exe'
   if (Test-Path $uninstaller -PathType Leaf) {
    $uninstallProcess=Start-Process -FilePath $uninstaller -ArgumentList @('/S') -Wait -PassThru
    if ($uninstallProcess.ExitCode -ne 0) { throw "uninstaller exit $($uninstallProcess.ExitCode)" }
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    while ((Test-Path $install) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (Test-Path $install) { throw 'uninstaller completed but task install directory survived bounded wait' }
   } elseif (Test-Path $install) { throw 'partial install has no owned uninstaller; refusing unproven deletion' }
  }
 } catch { $cleanupErrors.Add("uninstall: $($_.Exception.Message)") }
 try { if (Test-Path $profile) { $pm=Join-Path $profile '.growthmap-ci-owned'; if (-not (Test-Path $pm -PathType Leaf) -or (Get-Content $pm -Raw).Trim() -cne 'growthmap-installed-acceptance-v1') { throw 'profile ownership marker mismatch' }; Remove-Item $profile -Recurse -Force } } catch { $cleanupErrors.Add("profile: $($_.Exception.Message)") }
 try { Assert-Owned; if (Test-Path $stage) { Remove-Item $stage -Recurse -Force } } catch { $cleanupErrors.Add("staging: $($_.Exception.Message)") }
 try { if (Test-Path $install) { throw 'task install directory survived cleanup' }; $after=Footprint; if ((Canonical $after) -cne (Canonical $before)) { throw 'GrowthMap registry/path/shortcut/process footprint was not exactly restored' } } catch { $cleanupErrors.Add("footprint: $($_.Exception.Message)") }
 try { Assert-Owned; Remove-Item $externalOwner -Force } catch { $cleanupErrors.Add("owner-marker: $($_.Exception.Message)") }
 if ($cleanupErrors.Count) { throw [AggregateException]::new('Installed acceptance cleanup failed',@($cleanupErrors|ForEach-Object{[Exception]::new($_)})) }
}
