param(
    [string]$GatewayUrl = "http://127.0.0.1:8765",
    [string]$ProjectId = "GEELY_TEST",
    [string]$RunId = "RUN_HOST_DEMO",
    [string]$HostSessionId = "host-$([guid]::NewGuid().ToString('N'))",
    [string]$SourceFile = "",
    [string]$TargetFile = "",
    [string]$Question = "Analyze the current test failures and suggest next troubleshooting steps.",
    [switch]$OpenCopilot
)

$ErrorActionPreference = "Stop"

function Get-RepoPath {
    param([string]$RelativePath)
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\$RelativePath"))
}

function Invoke-GatewayJson {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body = $null
    )

    $uri = $GatewayUrl.TrimEnd("/") + $Path
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri
    }

    return Invoke-RestMethod `
        -Method $Method `
        -ContentType "application/json" `
        -Uri $uri `
        -Body ($Body | ConvertTo-Json -Depth 20)
}

if ([string]::IsNullOrWhiteSpace($SourceFile)) {
    $SourceFile = Get-RepoPath "src\ai-gateway\tests\fixtures\test-run-cases.csv"
}

if ([string]::IsNullOrWhiteSpace($TargetFile)) {
    $TargetFile = Get-RepoPath "src\ai-gateway\tests\fixtures\test-run-cases-target.csv"
}

$SessionQuery = "?host_session_id=$([uri]::EscapeDataString($HostSessionId))"
$sourceAsset = Invoke-GatewayJson `
    -Method "POST" `
    -Path ("/api/v1/host/assets" + $SessionQuery) `
    -Body @{ file_path = $SourceFile }
$targetAsset = Invoke-GatewayJson `
    -Method "POST" `
    -Path ("/api/v1/host/assets" + $SessionQuery) `
    -Body @{ file_path = $TargetFile }

$context = @{
    project_id = $ProjectId
    run_id = $RunId
    source_asset_id = $sourceAsset.result.asset_id
    target_asset_id = $targetAsset.result.asset_id
    current_view = "test_result_detail"
    user_id = $env:USERNAME
}

Write-Host "Checking AI Gateway..."
Invoke-GatewayJson -Method "GET" -Path "/health" | ConvertTo-Json -Depth 20

Write-Host "`nUpdating host context..."
Invoke-GatewayJson -Method "POST" -Path ("/api/v1/host/context" + $SessionQuery) -Body $context | ConvertTo-Json -Depth 20

Write-Host "`nReading tool registry..."
Invoke-GatewayJson -Method "GET" -Path "/api/v1/tools" | ConvertTo-Json -Depth 20

Write-Host "`nRunning current test analysis..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path ("/api/v1/analyze" + $SessionQuery) `
    -Body @{ source_asset_id = $sourceAsset.result.asset_id; question = $Question } |
    ConvertTo-Json -Depth 20

Write-Host "`nGenerating test data insights..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path ("/api/v1/test-data/insights" + $SessionQuery) `
    -Body @{ source_asset_id = $sourceAsset.result.asset_id } |
    ConvertTo-Json -Depth 20

Write-Host "`nComparing test runs..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path ("/api/v1/test-data/compare" + $SessionQuery) `
    -Body @{
        baseline_asset_id = $sourceAsset.result.asset_id
        target_asset_id = $targetAsset.result.asset_id
    } |
    ConvertTo-Json -Depth 20

if ($OpenCopilot) {
    Start-Process ($GatewayUrl.TrimEnd("/") + "/copilot-shell/" + $SessionQuery)
}
