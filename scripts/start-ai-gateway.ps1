param(
    [string]$HostName = $(if ($env:AI_GATEWAY_HOST) { $env:AI_GATEWAY_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:AI_GATEWAY_PORT) { [int]$env:AI_GATEWAY_PORT } else { 8765 }),
    [string]$EnvFile = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$GatewayRoot = Join-Path $RepoRoot "src\ai-gateway"

function Import-EnvFile {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "Env file does not exist: $resolved"
    }
    Get-Content -LiteralPath $resolved | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
            return
        }
        $parts = $line.Split("=", 2)
        if ($parts.Count -ne 2) {
            return
        }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

Import-EnvFile -Path $EnvFile

if ($env:AI_GATEWAY_HOST) {
    $HostName = $env:AI_GATEWAY_HOST
}
if ($env:AI_GATEWAY_PORT) {
    $Port = [int]$env:AI_GATEWAY_PORT
}

$env:PYTHONPATH = "src"

Write-Host "Starting Geely AI Gateway..."
Write-Host "URL: http://$HostName`:$Port"
Write-Host "Showcase: http://$HostName`:$Port/showcase"
Write-Host "Copilot: http://$HostName`:$Port/copilot-shell/"
Write-Host "Model configured: $([bool]($env:AI_MODEL_BASE_URL -and $env:AI_MODEL_API_KEY -and $env:AI_MODEL_NAME))"

Push-Location $GatewayRoot
try {
    & $Python -m ai_gateway.server --host $HostName --port $Port
}
finally {
    Pop-Location
}
