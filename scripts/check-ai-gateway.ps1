param(
    [string]$GatewayUrl = $(if ($env:AI_GATEWAY_URL) { $env:AI_GATEWAY_URL } else { "http://127.0.0.1:8765" })
)

$ErrorActionPreference = "Stop"
$BaseUrl = $GatewayUrl.TrimEnd("/")

function Invoke-GatewayJson {
    param([string]$Path)
    return Invoke-RestMethod -Method Get -Uri ($BaseUrl + $Path)
}

function Assert-Ok {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
    Write-Host "PASS $Message"
}

$health = Invoke-GatewayJson -Path "/health"
Assert-Ok ($health.status -eq "ok") "/health"

$model = Invoke-GatewayJson -Path "/api/v1/model/config"
Assert-Ok ($null -ne $model.result.configured) "/api/v1/model/config"
Assert-Ok (-not ($model.result.PSObject.Properties.Name -contains "api_key")) "model config hides api_key"

$manifest = Invoke-GatewayJson -Path "/plugin-manifest.json"
Assert-Ok ($manifest.webview.entry -eq "/copilot-shell/") "/plugin-manifest.json"

$tools = Invoke-GatewayJson -Path "/api/v1/tools"
$toolNames = @($tools.result.tools | ForEach-Object { $_.name })
Assert-Ok ($toolNames -contains "analyze_test_run") "tool analyze_test_run"
Assert-Ok ($toolNames -contains "analyze_test_data_insights") "tool analyze_test_data_insights"
Assert-Ok ($toolNames -contains "compare_test_runs") "tool compare_test_runs"

$showcase = Invoke-WebRequest -Method Get -UseBasicParsing -Uri ($BaseUrl + "/showcase")
Assert-Ok ($showcase.StatusCode -eq 200) "/showcase"

$copilot = Invoke-WebRequest -Method Get -UseBasicParsing -Uri ($BaseUrl + "/copilot-shell/")
Assert-Ok ($copilot.StatusCode -eq 200) "/copilot-shell/"
Assert-Ok ($copilot.Content -match "/copilot-shell/assets/.+\.js") "Copilot shell JavaScript asset"

Write-Host "AI Gateway check completed: $BaseUrl"
