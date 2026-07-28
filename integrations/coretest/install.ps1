param(
    [string]$CoreTestRoot = "$PSScriptRoot\..\..\customer-data\hk-coretest-ai"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "coretest_copilot"
$target = Join-Path (Resolve-Path $CoreTestRoot) "app\coretest_copilot"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item -Recurse -Force (Join-Path $source "*") $target

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

Write-Output "CoreTest Copilot installed: $target"
