param([Parameter(Mandatory)][string]$NodeModules,[Parameter(Mandatory)][string]$LockPath,[Parameter(Mandatory)][string]$PackagePath,[Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference='Stop'
$root=(Resolve-Path $NodeModules).Path
$files=@(Get-ChildItem $root -File -Force -Recurse | ForEach-Object {
  $rel=[IO.Path]::GetRelativePath($root,$_.FullName) -replace '\\','/'
  if ($rel -match '(^|/)\.\.(/|$)' -or $rel.StartsWith('/')) { throw "node_modules path escapes root: $rel" }
  [ordered]@{path=$rel;sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
} | Sort-Object path)
$roots=@(Get-ChildItem $root -Directory -Force -Recurse | Where-Object {
  ($_.Parent.Name -eq 'node_modules' -and -not $_.Name.StartsWith('@')) -or
  ($_.Parent.Parent -and $_.Parent.Parent.Name -eq 'node_modules' -and $_.Parent.Name.StartsWith('@'))
} | ForEach-Object {[IO.Path]::GetRelativePath($root,$_.FullName) -replace '\\','/'} | Sort-Object -Unique)
$doc=[ordered]@{version=1;lockSha256=(Get-FileHash $LockPath -Algorithm SHA256).Hash.ToLowerInvariant();packageSha256=(Get-FileHash $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant();packageRoots=$roots;files=$files}
$dir=Split-Path $OutputPath -Parent;New-Item -ItemType Directory $dir -Force|Out-Null
$doc|ConvertTo-Json -Depth 5 -Compress|Set-Content $OutputPath -Encoding utf8NoBOM
(Get-FileHash $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
