param(
    [string]$CoreTestRoot = "$PSScriptRoot\..\..\customer-data\hk-coretest-ai",
    [string]$OpenCodeExecutable = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$source = Join-Path $PSScriptRoot "coretest_copilot"
$target = Join-Path (Resolve-Path $CoreTestRoot) "app\coretest_copilot"

function Sync-Directory {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Required runtime directory not found: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    Get-ChildItem -LiteralPath $Destination -Directory -Filter "__pycache__" -Recurse |
        Remove-Item -Recurse -Force
}

New-Item -ItemType Directory -Force $target | Out-Null
Get-ChildItem -LiteralPath $source -File | Copy-Item -Destination $target -Force

$runtime = Join-Path $target "runtime"
Sync-Directory `
    (Join-Path $repoRoot "frontend\copilot-shell\dist") `
    (Join-Path $runtime "frontend\copilot-shell\dist")
Sync-Directory `
    (Join-Path $repoRoot "frontend\opencode-coretest\dist") `
    (Join-Path $runtime "frontend\opencode-coretest\dist")
Sync-Directory `
    (Join-Path $repoRoot "src\ai-gateway\src\ai_gateway") `
    (Join-Path $runtime "src\ai_gateway")
Sync-Directory `
    (Join-Path $repoRoot "contracts") `
    (Join-Path $runtime "contracts")
Sync-Directory `
    (Join-Path $repoRoot "third_party") `
    (Join-Path $runtime "compliance")
Copy-Item `
    -LiteralPath (Join-Path $repoRoot "config\open-source-lock.json") `
    -Destination (Join-Path $runtime "compliance\OpenCode-lock.json") `
    -Force
Copy-Item `
    -LiteralPath (Join-Path $repoRoot "config\open-source-license-overrides.json") `
    -Destination (Join-Path $runtime "compliance\OpenCode-license-overrides.json") `
    -Force

if ([string]::IsNullOrWhiteSpace($OpenCodeExecutable)) {
    $localCache = if ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA "HK-CoreTest\OpenCode\1.18.10\opencode.exe"
    } else {
        ""
    }
    $candidates = @(
        (Join-Path $repoRoot "src\ai-gateway\src\ai_gateway\bin\opencode.exe"),
        (Join-Path $repoRoot "tmp\opencode-runtime-v1.18.10\runtime-verified\opencode.exe"),
        $localCache
    )
    $OpenCodeExecutable = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($OpenCodeExecutable)) {
    throw "Locked OpenCode runtime is missing. Run scripts/stage-opencode-runtime.ps1 first."
}
& (Join-Path $repoRoot "scripts\verify-opencode-bundle.ps1") `
    -OpenCodeExecutable $OpenCodeExecutable `
    -RepoRoot $repoRoot
$runtimeBin = Join-Path $runtime "src\ai_gateway\bin"
New-Item -ItemType Directory -Force $runtimeBin | Out-Null
Copy-Item -LiteralPath $OpenCodeExecutable -Destination (Join-Path $runtimeBin "opencode.exe") -Force

$window = Join-Path (Resolve-Path $CoreTestRoot) "app\view\window.py"
$text = Get-Content -Raw -Encoding UTF8 $window
if ($text -notmatch "app\.coretest_copilot") {
    $text = $text.Replace(
        "from app.view.project_vbf.view import VbfFileView",
        "from app.view.project_vbf.view import VbfFileView`r`nfrom app.coretest_copilot import CoreTestCopilot"
    )
    $text = $text.Replace(
        "        self.setWindowTitle(f`"{config.APP_NAME}_v{config.APP_VERSION}`")",
        "        self.setWindowTitle(f`"{config.APP_NAME}_v{config.APP_VERSION}`")`r`n        self.copilot = CoreTestCopilot(self)"
    )
    $text = $text.Replace("        diag_task_view = DiagTaskView(self.diagnostic_tabs)", "        self.diag_task_view = DiagTaskView(self.diagnostic_tabs)")
    $text = $text.Replace("self.diagnostic_tabs.addTab(diag_task_view,", "self.diagnostic_tabs.addTab(self.diag_task_view,")
    $text = $text.Replace("        can_trace_view = CanTraceView(self.trace_tabs)", "        self.can_trace_view = CanTraceView(self.trace_tabs)")
    $text = $text.Replace("self.trace_tabs.addTab(can_trace_view,", "self.trace_tabs.addTab(self.can_trace_view,")
    $text = $text.Replace("        replay_view = CanReplayView(self.trace_tabs)", "        self.replay_view = CanReplayView(self.trace_tabs)")
    $text = $text.Replace("self.trace_tabs.addTab(replay_view,", "self.trace_tabs.addTab(self.replay_view,")
    [System.IO.File]::WriteAllText(
        $window,
        $text,
        [System.Text.UTF8Encoding]::new($true)
    )
}

Write-Output "CoreTest Agent, Gateway, and verified OpenCode runtime installed: $target"
