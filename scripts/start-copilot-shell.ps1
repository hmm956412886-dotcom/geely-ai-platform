param(
    [string]$GatewayUrl = $(if ($env:AI_GATEWAY_URL) { $env:AI_GATEWAY_URL } else { "http://127.0.0.1:8765" }),
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5173,
    [string]$Pnpm = "pnpm"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$FrontendRoot = Join-Path $RepoRoot "frontend\copilot-shell"
$env:AI_GATEWAY_URL = $GatewayUrl.TrimEnd("/")

Push-Location $FrontendRoot
try {
    if (-not (Test-Path -LiteralPath "node_modules")) {
        & $Pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Copilot shell dependencies"
        }
    }

    Write-Host "Starting CoreTest Agent shell..."
    Write-Host "URL: http://$HostName`:$Port/copilot-shell/"
    Write-Host "Gateway: $env:AI_GATEWAY_URL"
    & $Pnpm exec vite --host $HostName --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Copilot shell exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
