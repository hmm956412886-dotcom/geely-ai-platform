param(
    [string]$OutputDirectory = "$PSScriptRoot\..\tmp\opencode-runtime-v1.18.10\runtime-verified"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$lock = Get-Content -Raw (Join-Path $repoRoot "config\open-source-lock.json") | ConvertFrom-Json
$asset = $lock.windows_x64_asset
$outputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$downloadRoot = Join-Path $repoRoot "tmp\opencode-download-$($lock.tag.TrimStart('v'))"
$archive = Join-Path $downloadRoot $asset.name
$executable = Join-Path $outputDirectory "opencode.exe"

New-Item -ItemType Directory -Force $downloadRoot, $outputDirectory | Out-Null
if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$asset.sha256) {
    Invoke-WebRequest -Uri $asset.url -OutFile $archive -UseBasicParsing
}
if ((Get-Item -LiteralPath $archive).Length -ne [long]$asset.size -or
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$asset.sha256) {
    throw "Downloaded OpenCode archive does not match config/open-source-lock.json"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$bundle = [System.IO.Compression.ZipFile]::OpenRead($archive)
try {
    $entry = $bundle.GetEntry("opencode.exe")
    if ($null -eq $entry) { throw "OpenCode archive does not contain opencode.exe" }
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $executable, $true)
}
finally {
    $bundle.Dispose()
}

& (Join-Path $PSScriptRoot "verify-opencode-bundle.ps1") `
    -OpenCodeExecutable $executable `
    -RepoRoot $repoRoot
Write-Output "OpenCode runtime staged: $executable"
