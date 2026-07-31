param(
    [string]$CoreTestRoot = "$PSScriptRoot\..\customer-data\hk-coretest-ai",
    [string]$Python = "python",
    [string]$Pnpm = "pnpm"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$coreTestRoot = [System.IO.Path]::GetFullPath($CoreTestRoot)
$frontendRoot = Join-Path $repoRoot "frontend\copilot-shell"
$sidecarRoot = Join-Path $repoRoot "dist\geely-ai-gateway"
$envExample = Join-Path $repoRoot "config\runtime.env.example"
$coreTestScripts = Join-Path $coreTestRoot "resource\scripts"

Write-Warning (
    "OpenCode Agent Runtime is intentionally excluded. " +
    "Do not add it until docs/14-open-source-compliance.md is satisfied."
)

Push-Location $frontendRoot
try {
    & $Pnpm build
    if ($LASTEXITCODE -ne 0) { throw "Copilot frontend build failed." }
}
finally {
    Pop-Location
}

& (Join-Path $repoRoot "integrations\coretest\install.ps1") -CoreTestRoot $coreTestRoot
& (Join-Path $PSScriptRoot "build-ai-gateway.ps1") -Python $Python

if (-not (Test-Path -LiteralPath $coreTestScripts)) {
    New-Item -ItemType Directory -Path $coreTestScripts | Out-Null
}

Push-Location $coreTestRoot
try {
    & $Python build_app.py
    if ($LASTEXITCODE -ne 0) { throw "CoreTest build failed." }
}
finally {
    Pop-Location
}

$deliveryZip = Get-ChildItem -LiteralPath (Join-Path $coreTestRoot "dist") -Filter "HK-CoreTest_v*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $deliveryZip) {
    throw "CoreTest delivery ZIP was not created."
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::Open(
    $deliveryZip.FullName,
    [System.IO.Compression.ZipArchiveMode]::Update
)
try {
    $sidecarPrefix = $sidecarRoot.TrimEnd("\") + "\"
    foreach ($file in Get-ChildItem -LiteralPath $sidecarRoot -Recurse -File) {
        $relative = $file.FullName.Substring($sidecarPrefix.Length)
        $entryName = "ai-gateway/" + $relative.Replace("\", "/")
        $existing = $archive.GetEntry($entryName)
        if ($null -ne $existing) { $existing.Delete() }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
    if (Test-Path -LiteralPath $envExample) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $envExample,
            "ai-gateway/.env.example",
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
}

Write-Output "CoreTest Copilot delivery built: $($deliveryZip.FullName)"
