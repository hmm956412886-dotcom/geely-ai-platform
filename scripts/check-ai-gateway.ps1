param(
    [string]$GatewayUrl = $(if ($env:AI_GATEWAY_URL) { $env:AI_GATEWAY_URL } else { "http://127.0.0.1:8765" }),
    [string]$CopilotUrl = "",
    [string]$AccessToken = $(if ($env:AI_GATEWAY_ACCESS_TOKEN) { $env:AI_GATEWAY_ACCESS_TOKEN } else { "" })
)

$ErrorActionPreference = "Stop"
$BaseUrl = $GatewayUrl.TrimEnd("/")
$CopilotBaseUrl = if ($CopilotUrl) { $CopilotUrl.TrimEnd("/") } else { $BaseUrl + "/copilot-shell" }
$ApiHeaders = if ($AccessToken) { @{ Authorization = "Bearer $AccessToken" } } else { @{} }

function Invoke-GatewayJson {
    param([string]$Path)
    return Invoke-RestMethod -Method Get -Headers $ApiHeaders -Uri ($BaseUrl + $Path)
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

$agent = Invoke-GatewayJson -Path "/api/v1/agent/status"
Assert-Ok ($null -ne $agent.result.runtime.installed) "/api/v1/agent/status"
Assert-Ok (-not ($agent.result.runtime.PSObject.Properties.Name -contains "password")) "agent status hides password"
Assert-Ok (-not ($agent.result.workspace.PSObject.Properties.Name -contains "project_root")) "agent status hides workspace path"

$manifest = Invoke-GatewayJson -Path "/plugin-manifest.json"
Assert-Ok ($manifest.webview.entry -eq "/copilot-shell/") "/plugin-manifest.json"

$showcase = Invoke-WebRequest -Method Get -UseBasicParsing -Uri ($BaseUrl + "/showcase")
Assert-Ok ($showcase.StatusCode -eq 200) "/showcase"

$copilot = Invoke-WebRequest -Method Get -UseBasicParsing -Uri ($CopilotBaseUrl + "/")
Assert-Ok ($copilot.StatusCode -eq 200) "Copilot shell URL"
Assert-Ok ($copilot.Content -match "/copilot-shell/(assets/.+\.js|src/main\.tsx)") "Copilot shell JavaScript entry"

Write-Host "AI Gateway check completed: $BaseUrl"
Write-Host "Copilot shell check completed: $CopilotBaseUrl/"
