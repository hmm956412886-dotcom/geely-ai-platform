param(
    [string]$Python = "python",
    [string]$OutputRoot = "$PSScriptRoot\..\dist",
    [string]$OpenCodeExecutable = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$gatewaySource = Join-Path $repoRoot "src\ai-gateway\src"
$frontendDist = Join-Path $repoRoot "frontend\copilot-shell\dist"
$contracts = Join-Path $repoRoot "contracts"
$fixtures = Join-Path $repoRoot "src\ai-gateway\tests\fixtures"
$compliance = Join-Path $repoRoot "third_party"
$workRoot = Join-Path $repoRoot "tmp\ai-gateway-pyinstaller"
$outputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
    throw "Copilot frontend is not built. Run pnpm build in frontend/copilot-shell first."
}
if ([string]::IsNullOrWhiteSpace($OpenCodeExecutable)) {
    throw "OpenCodeExecutable is required for a self-contained Gateway build."
}
$OpenCodeExecutable = [System.IO.Path]::GetFullPath($OpenCodeExecutable)
& (Join-Path $PSScriptRoot "verify-opencode-bundle.ps1") `
    -OpenCodeExecutable $OpenCodeExecutable `
    -RepoRoot $repoRoot

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name geely-ai-gateway `
    --distpath $outputRoot `
    --workpath $workRoot `
    --specpath $workRoot `
    --paths $gatewaySource `
    --add-data "$frontendDist;frontend/copilot-shell/dist" `
    --add-data "$contracts;contracts" `
    --add-data "$fixtures;tests/fixtures" `
    --add-data "$compliance;compliance" `
    --add-binary "$OpenCodeExecutable;ai_gateway/bin" `
    (Join-Path $PSScriptRoot "ai-gateway-entry.py")

if ($LASTEXITCODE -ne 0) {
    throw "AI Gateway Sidecar build failed."
}

$executable = Join-Path $outputRoot "geely-ai-gateway\geely-ai-gateway.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "AI Gateway Sidecar executable was not created: $executable"
}

Write-Output "AI Gateway Sidecar built: $executable"
