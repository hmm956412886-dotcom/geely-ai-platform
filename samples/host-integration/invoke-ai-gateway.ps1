param(
    [string]$GatewayUrl = "http://127.0.0.1:8765",
    [string]$ProjectId = "GEELY_TEST",
    [string]$RunId = "RUN_HOST_DEMO",
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

$context = @{
    project_id = $ProjectId
    run_id = $RunId
    source_file = $SourceFile
    target_file = $TargetFile
    current_view = "test_result_detail"
    user_id = $env:USERNAME
}

Write-Host "Checking AI Gateway..."
Invoke-GatewayJson -Method "GET" -Path "/health" | ConvertTo-Json -Depth 20

Write-Host "`nUpdating host context..."
Invoke-GatewayJson -Method "POST" -Path "/api/v1/host/context" -Body $context | ConvertTo-Json -Depth 20

Write-Host "`nReading tool registry..."
Invoke-GatewayJson -Method "GET" -Path "/api/v1/tools" | ConvertTo-Json -Depth 20

Write-Host "`nRunning current test analysis..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path "/api/v1/analyze" `
    -Body @{ source_file = $SourceFile; question = $Question } |
    ConvertTo-Json -Depth 20

Write-Host "`nGenerating test data insights..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path "/api/v1/test-data/insights" `
    -Body @{ source_file = $SourceFile } |
    ConvertTo-Json -Depth 20

Write-Host "`nComparing test runs..."
Invoke-GatewayJson `
    -Method "POST" `
    -Path "/api/v1/test-data/compare" `
    -Body @{ baseline_file = $SourceFile; target_file = $TargetFile } |
    ConvertTo-Json -Depth 20

if ($OpenCopilot) {
    Start-Process ($GatewayUrl.TrimEnd("/") + "/copilot")
}
