param(
    [string]$CoreTestRoot = "$PSScriptRoot\..\customer-data\hk-coretest-ai",
    [string]$Python = "python",
    [string]$Pnpm = "pnpm",
    [string]$Node = "",
    [string]$OpenCodeExecutable = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$coreTestRoot = [System.IO.Path]::GetFullPath($CoreTestRoot)
$frontendRoot = Join-Path $repoRoot "frontend\copilot-shell"
$sidecarRoot = Join-Path $repoRoot "dist\geely-ai-gateway"
$envExample = Join-Path $repoRoot "config\runtime.env.example"
$coreTestScripts = Join-Path $coreTestRoot "resource\scripts"
$pluginManifest = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "contracts\host-plugin.manifest.json") |
    ConvertFrom-Json

function Invoke-CopilotShellBuild {
    param([string]$Root, [string]$NodeCommand)

    $nodeExe = if ([string]::IsNullOrWhiteSpace($NodeCommand)) { "node" } else { $NodeCommand }
    $tsc = Join-Path $Root "node_modules\typescript\bin\tsc"
    $vite = Join-Path $Root "node_modules\vite\bin\vite.js"
    if (-not (Test-Path -LiteralPath $tsc -PathType Leaf)) {
        throw "Copilot frontend dependencies are missing. Run pnpm install in frontend/copilot-shell first."
    }
    if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
        throw "Copilot frontend Vite dependency is missing. Run pnpm install in frontend/copilot-shell first."
    }
    Push-Location $Root
    try {
        & $nodeExe $tsc -b
        if ($LASTEXITCODE -ne 0) { throw "Copilot frontend typecheck failed." }
        & $nodeExe $vite build --configLoader native
        if ($LASTEXITCODE -ne 0) { throw "Copilot frontend build failed." }
    }
    finally {
        Pop-Location
    }
}

if ($pluginManifest.webview.entry -eq "/agent-native/") {
    & (Join-Path $repoRoot "scripts\build-opencode-ui.ps1") -Pnpm $Pnpm -Node $Node
    & (Join-Path $repoRoot "scripts\generate-opencode-ui-compliance.ps1") -Pnpm $Pnpm -Node $Node
    $nativeUiArtifacts = @(
        "third_party\OpenCode-UI-SOURCE.json",
        "third_party\OpenCode-UI-SBOM.cdx.json",
        "third_party\OpenCode-UI-THIRD-PARTY-NOTICES.txt",
        "third_party\OpenCode-UI-ASSETS.sha256"
    )
    foreach ($relative in $nativeUiArtifacts) {
        $artifact = Join-Path $repoRoot $relative
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Native OpenCode UI delivery artifact is missing: $artifact"
        }
    }
    $openSourceLock = Get-Content -Raw -LiteralPath (Join-Path $repoRoot "config\open-source-lock.json") |
        ConvertFrom-Json
    $uiSource = Get-Content -Raw -LiteralPath (Join-Path $repoRoot $nativeUiArtifacts[0]) |
        ConvertFrom-Json
    if ($uiSource.commit -ne $openSourceLock.commit -or $uiSource.tag -ne $openSourceLock.tag) {
        throw "Native OpenCode UI source manifest does not match config/open-source-lock.json"
    }
    $uiSbom = Get-Content -Raw -LiteralPath (Join-Path $repoRoot $nativeUiArtifacts[1]) |
        ConvertFrom-Json
    if ($uiSbom.bomFormat -ne "CycloneDX" -or $uiSbom.specVersion -ne "1.6") {
        throw "Native OpenCode UI SBOM must be CycloneDX 1.6"
    }
    $uiNotices = Get-Content -Raw -LiteralPath (Join-Path $repoRoot $nativeUiArtifacts[2])
    if ($uiNotices -notmatch [regex]::Escape("OpenCode $($openSourceLock.tag)")) {
        throw "Native OpenCode UI Notices do not match the locked version"
    }
    $uiHashes = Get-Content -LiteralPath (Join-Path $repoRoot $nativeUiArtifacts[3])
    if (-not ($uiHashes | Where-Object { $_ -match '^[0-9a-f]{64}\s+\S+' })) {
        throw "Native OpenCode UI asset hashes are invalid"
    }
}

$legacyIndex = Join-Path $frontendRoot "dist\index.html"
if ($pluginManifest.webview.entry -eq "/agent-native/" -and (Test-Path -LiteralPath $legacyIndex -PathType Leaf)) {
    Write-Output "Using existing legacy Copilot Shell fallback build: $legacyIndex"
} else {
    Invoke-CopilotShellBuild -Root $frontendRoot -NodeCommand $Node
}

& (Join-Path $repoRoot "integrations\coretest\install.ps1") `
    -CoreTestRoot $coreTestRoot `
    -OpenCodeExecutable $OpenCodeExecutable
$embeddedOpenCode = Join-Path $coreTestRoot "app\coretest_copilot\runtime\src\ai_gateway\bin\opencode.exe"
& (Join-Path $PSScriptRoot "build-ai-gateway.ps1") `
    -Python $Python `
    -OpenCodeExecutable $embeddedOpenCode

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

Write-Output "CoreTest Agent delivery built: $($deliveryZip.FullName)"
