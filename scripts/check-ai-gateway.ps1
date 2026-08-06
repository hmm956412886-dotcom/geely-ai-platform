param(
    [string]$GatewayUrl = $(if ($env:AI_GATEWAY_URL) { $env:AI_GATEWAY_URL } else { "http://127.0.0.1:8765" }),
    [string]$CopilotUrl = "",
    [string]$AccessToken = $(if ($env:AI_GATEWAY_ACCESS_TOKEN) { $env:AI_GATEWAY_ACCESS_TOKEN } else { "" }),
    [string]$HostToken = $(if ($env:AI_GATEWAY_HOST_TOKEN) { $env:AI_GATEWAY_HOST_TOKEN } else { "" })
)

$ErrorActionPreference = "Stop"
$BaseUrl = $GatewayUrl.TrimEnd("/")
$CopilotBaseUrl = if ($CopilotUrl) { $CopilotUrl.TrimEnd("/") } else { $BaseUrl + "/agent-native" }
$ApiHeaders = if ($AccessToken) { @{ Authorization = "Bearer $AccessToken" } } else { @{} }
$HostHeaders = if ($HostToken) { @{ Authorization = "Bearer $HostToken" } } else { $ApiHeaders }
$SmokeSessionId = "gateway-smoke"
$SmokeWorkspace = $null

function Invoke-GatewayJson {
    param([string]$Path)
    return Invoke-RestMethod -Method Get -Headers $ApiHeaders -Uri ($BaseUrl + $Path)
}

function Invoke-HostJson {
    param([string]$Method, [string]$Path, [string]$Body = "")
    $arguments = @{
        Method = $Method
        Headers = $HostHeaders
        Uri = ($BaseUrl + $Path)
    }
    if ($Body) {
        $arguments.Body = $Body
        $arguments.ContentType = "application/json; charset=utf-8"
    }
    return Invoke-RestMethod @arguments
}

function Assert-Ok {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
    Write-Host "PASS $Message"
}

function Get-HttpErrorContent {
    param($ErrorRecord)
    $content = [string]$ErrorRecord.ErrorDetails.Message
    if (-not [string]::IsNullOrWhiteSpace($content)) {
        return $content
    }
    $response = $ErrorRecord.Exception.Response
    if ($null -eq $response) {
        return ""
    }
    $reader = [IO.StreamReader]::new($response.GetResponseStream())
    try {
        return $reader.ReadToEnd()
    }
    finally {
        $reader.Dispose()
    }
}

function Test-CoreTestAgentPage {
    param([string]$Url, [string]$WorkspacePath = "")
    $response = Invoke-WebRequest -Method Get -UseBasicParsing -Uri $Url
    Assert-Ok ($response.StatusCode -eq 200) "CoreTest Agent URL"
    Assert-Ok ($response.Content -match "coretest-agent-bootstrap") "CoreTest Agent native UI bootstrap"
    Assert-Ok ($response.Content -notmatch "OpenCode workspace is not registered") "CoreTest Agent page hides upstream workspace errors"
    if ($WorkspacePath) {
        Assert-Ok (-not $response.Content.Contains($WorkspacePath)) "CoreTest Agent page hides workspace path"
    }
}

function New-SmokeWorkspace {
    $tempRoot = [IO.Path]::GetTempPath()
    $path = [IO.Path]::GetFullPath((Join-Path $tempRoot ("coretest-agent-smoke-" + [Guid]::NewGuid().ToString("N"))))
    if (-not $path.StartsWith([IO.Path]::GetFullPath($tempRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Smoke workspace must stay under the system temp directory"
    }
    New-Item -ItemType Directory -Path $path | Out-Null
    Set-Content -LiteralPath (Join-Path $path "README.md") -Value "# CoreTest Agent smoke workspace" -Encoding UTF8
    return $path
}

try {
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
Assert-Ok ($manifest.webview.entry -eq "/agent-native/") "/plugin-manifest.json"
Assert-Ok ($manifest.webview.legacy_entry -eq "/copilot-shell/") "legacy Copilot shell entry"

$showcase = Invoke-WebRequest -Method Get -UseBasicParsing -Uri ($BaseUrl + "/showcase")
Assert-Ok ($showcase.StatusCode -eq 200) "/showcase"

try {
    Test-CoreTestAgentPage -Url ($CopilotBaseUrl + "/")
}
catch {
    $response = $_.Exception.Response
    if ($null -eq $response -or [int]$response.StatusCode -ne 502) {
        throw
    }
    $content = Get-HttpErrorContent -ErrorRecord $_
    Assert-Ok ($content -match "CoreTest Agent workspace is not registered") "CoreTest Agent waits for registered workspace"
    if ($AccessToken -and -not $HostToken) {
        Write-Host "SKIP registered workspace smoke: AI_GATEWAY_HOST_TOKEN is not configured"
    }
    else {
        $SmokeWorkspace = New-SmokeWorkspace
        $registerBody = @{ project_root = $SmokeWorkspace } | ConvertTo-Json -Compress
        $registered = Invoke-HostJson `
            -Method "POST" `
            -Path ("/api/v1/host/workspace?host_session_id=" + $SmokeSessionId) `
            -Body $registerBody
        Assert-Ok ($registered.result.workspace.registered -eq $true) "trusted host can register smoke workspace"

        $statusAfterRegister = Invoke-GatewayJson -Path ("/api/v1/agent/status?host_session_id=" + $SmokeSessionId)
        Assert-Ok ($statusAfterRegister.result.workspace.registered -eq $true) "agent status sees registered workspace"
        Assert-Ok (-not ($statusAfterRegister.result.workspace.PSObject.Properties.Name -contains "project_root")) "registered workspace status hides path"

        Test-CoreTestAgentPage `
            -Url ($CopilotBaseUrl + "/?host_session_id=" + $SmokeSessionId) `
            -WorkspacePath $SmokeWorkspace
    }
}

Write-Host "AI Gateway check completed: $BaseUrl"
Write-Host "CoreTest Agent native UI check completed: $CopilotBaseUrl/"
}
finally {
    try {
        Invoke-HostJson -Method "DELETE" -Path ("/api/v1/host/session?host_session_id=" + $SmokeSessionId) | Out-Null
    }
    catch {
    }
    if ($SmokeWorkspace) {
        $resolvedSmokeWorkspace = [IO.Path]::GetFullPath($SmokeWorkspace)
        $resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($resolvedSmokeWorkspace.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedSmokeWorkspace).StartsWith("coretest-agent-smoke-", [StringComparison]::Ordinal)) {
            Remove-Item -LiteralPath $resolvedSmokeWorkspace -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
