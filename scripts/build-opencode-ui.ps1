param(
    [string]$Pnpm = "pnpm",
    [string]$Node = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$tmpRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "tmp"))
$buildId = "opencode-ui-build-{0}-{1}" -f ([DateTime]::UtcNow.ToString("yyyyMMddHHmmssfff")), $PID
$buildRoot = [IO.Path]::GetFullPath((Join-Path $tmpRoot $buildId))
$buildPointerPath = Join-Path $tmpRoot "opencode-ui-build-current.txt"
$profileRoot = Join-Path $repoRoot "frontend\opencode-coretest\profile"
$outputRoot = Join-Path $repoRoot "frontend\opencode-coretest\dist"
$sourceManifestPath = Join-Path $repoRoot "third_party\OpenCode-UI-SOURCE.json"

$nodeCommand = "node"
if ($Node) {
    $nodePath = [IO.Path]::GetFullPath($Node)
    if (-not (Test-Path -LiteralPath $nodePath -PathType Leaf)) {
        throw "Node executable is missing: $nodePath"
    }
    $env:Path = [IO.Path]::GetDirectoryName($nodePath) + [IO.Path]::PathSeparator + $env:Path
    $nodeCommand = $nodePath
}

$profileTests = Get-ChildItem -LiteralPath $profileRoot -Filter "*.test.mjs" | Select-Object -ExpandProperty FullName
& $nodeCommand --test $profileTests
if ($LASTEXITCODE -ne 0) { throw "CoreTest profile tests failed" }

if (-not $buildRoot.StartsWith($tmpRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "OpenCode UI build directory must stay under tmp"
}

$manifest = Get-Content -Raw -LiteralPath $sourceManifestPath | ConvertFrom-Json
foreach ($source in $manifest.source_archives) {
    $path = Join-Path $repoRoot $source.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "OpenCode UI source archive is missing: $path"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $source.sha256) {
        throw "OpenCode UI source archive hash mismatch: $path"
    }
}
$lockfilePath = Join-Path $repoRoot $manifest.build_lockfile.path
if (-not (Test-Path -LiteralPath $lockfilePath -PathType Leaf)) {
    throw "OpenCode UI lockfile is missing: $lockfilePath"
}
$lockfileHash = (Get-FileHash -LiteralPath $lockfilePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($lockfileHash -ne $manifest.build_lockfile.sha256) {
    throw "OpenCode UI lockfile hash mismatch: $lockfilePath"
}

New-Item -ItemType Directory -Path $buildRoot | Out-Null

$workspaceArchive = Join-Path $repoRoot $manifest.source_archives[0].path
& tar -xzf $workspaceArchive -C $buildRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to extract the OpenCode UI workspace source" }
$upstreamPackage = Get-Content -Raw -LiteralPath (Join-Path $buildRoot "package.json") | ConvertFrom-Json

$uiExtract = Join-Path $buildRoot "ui-package"
$sdkExtract = Join-Path $buildRoot "sdk-package"
New-Item -ItemType Directory -Path $uiExtract, $sdkExtract | Out-Null
& tar -xzf (Join-Path $repoRoot $manifest.source_archives[1].path) -C $uiExtract
if ($LASTEXITCODE -ne 0) { throw "Failed to extract @opencode-ai/ui" }
& tar -xzf (Join-Path $repoRoot $manifest.source_archives[2].path) -C $sdkExtract
if ($LASTEXITCODE -ne 0) { throw "Failed to extract @opencode-ai/sdk" }
Copy-Item -LiteralPath (Join-Path $uiExtract "package") -Destination (Join-Path $buildRoot "packages\ui") -Recurse
Copy-Item -LiteralPath (Join-Path $sdkExtract "package") -Destination (Join-Path $buildRoot "packages\sdk-js") -Recurse

Copy-Item -LiteralPath (Join-Path $profileRoot "package.json") -Destination (Join-Path $buildRoot "package.json") -Force
Copy-Item -LiteralPath $lockfilePath -Destination (Join-Path $buildRoot "pnpm-lock.yaml") -Force
Copy-Item -LiteralPath (Join-Path $profileRoot "patches") -Destination (Join-Path $buildRoot "patches") -Recurse
$workspaceTemplate = [IO.File]::ReadAllText((Join-Path $profileRoot "pnpm-workspace.yaml")).TrimEnd()
$workspaceLines = New-Object System.Collections.Generic.List[string]
$workspaceLines.Add($workspaceTemplate)
$workspaceLines.Add("")
$workspaceLines.Add("catalog:")
foreach ($property in $upstreamPackage.workspaces.catalog.PSObject.Properties) {
    $name = $property.Name.Replace("'", "''")
    $value = ([string]$property.Value).Replace("'", "''")
    $workspaceLines.Add("  '$name': '$value'")
}
[IO.File]::WriteAllLines(
    (Join-Path $buildRoot "pnpm-workspace.yaml"),
    $workspaceLines,
    [Text.UTF8Encoding]::new($false)
)
Copy-Item -LiteralPath (Join-Path $profileRoot "core-package.json") -Destination (Join-Path $buildRoot "packages\core\package.json") -Force
Copy-Item -LiteralPath (Join-Path $profileRoot "coretest-provider-error.ts") -Destination (Join-Path $buildRoot "packages\core\src\coretest-provider-error.ts") -Force
Copy-Item -LiteralPath (Join-Path $profileRoot "coretest-session-title.ts") -Destination (Join-Path $buildRoot "packages\app\src\utils\coretest-session-title.ts") -Force
Copy-Item -LiteralPath (Join-Path $profileRoot "coretest-profile.css") -Destination (Join-Path $buildRoot "packages\app\src\coretest-profile.css") -Force

$indexCss = Join-Path $buildRoot "packages\app\src\index.css"
$css = [IO.File]::ReadAllText($indexCss)
if ($css -notmatch 'coretest-profile\.css') {
    [IO.File]::WriteAllText($indexCss, $css + "`n@import `"./coretest-profile.css`";`n", [Text.UTF8Encoding]::new($false))
}

$indexHtml = Join-Path $buildRoot "packages\app\index.html"
$html = [IO.File]::ReadAllText($indexHtml)
if (-not $html.Contains("<title>OpenCode</title>")) {
    throw "The locked OpenCode title anchor was not found"
}
[IO.File]::WriteAllText($indexHtml, $html.Replace("<title>OpenCode</title>", "<title>CoreTest Agent</title>"), [Text.UTF8Encoding]::new($false))

$entry = Join-Path $buildRoot "packages\app\src\entry.tsx"
$entryText = [IO.File]::ReadAllText($entry)
$entryText = $entryText.Replace('icon: "https://opencode.ai/favicon-96x96-v3.png"', 'icon: "/favicon-96x96-v3.png"')
$entryText = $entryText.Replace('if (typeof navigator !== "object") return "en" as const', 'if (typeof navigator !== "object") return "zh" as const')
$entryText = $entryText.Replace('return "en" as const', 'return "zh" as const')
$entryLocaleAnchor = 'if (root instanceof HTMLElement) {'
if (-not $entryText.Contains($entryLocaleAnchor)) {
    throw "The locked OpenCode entry locale anchor was not found"
}
$entryText = $entryText.Replace(
    $entryLocaleAnchor,
    "setStorage(`"opencode.global.dat:language`", JSON.stringify({ locale: `"zh`" }))`n`n$entryLocaleAnchor"
)
[IO.File]::WriteAllText($entry, $entryText, [Text.UTF8Encoding]::new($false))

$settings = Join-Path $buildRoot "packages\app\src\context\settings.tsx"
$settingsText = [IO.File]::ReadAllText($settings)
$settingsText = $settingsText.Replace("releaseNotes: true,", "releaseNotes: false,")
[IO.File]::WriteAllText($settings, $settingsText, [Text.UTF8Encoding]::new($false))

$promptPlaceholder = Join-Path $buildRoot "packages\app\src\components\prompt-input\placeholder.ts"
$promptPlaceholderText = [IO.File]::ReadAllText($promptPlaceholder)
$promptPlaceholderAnchor = 'return "Ask anything, / for commands, @ for context..."'
if (-not $promptPlaceholderText.Contains($promptPlaceholderAnchor)) {
    throw "The locked OpenCode prompt placeholder anchor was not found"
}
$promptPlaceholderText = $promptPlaceholderText.Replace(
    $promptPlaceholderAnchor,
    'return "\u5206\u6790\u6587\u4ef6\u3001DBC/Trace\uff0c\u6216\u63cf\u8ff0\u6d4b\u8bd5\u4efb\u52a1..."'
)
[IO.File]::WriteAllText(
    $promptPlaceholder,
    $promptPlaceholderText,
    [Text.UTF8Encoding]::new($false)
)

$sessionPrompt = Join-Path $buildRoot "packages\session-ui\src\v2\components\prompt-input\index.tsx"
$sessionPromptText = [IO.File]::ReadAllText($sessionPrompt)
$sessionPromptReplacements = @(
    @('emptyLabel="No matching items"', 'emptyLabel={"\u6ca1\u6709\u5339\u914d\u7684\u5185\u5bb9"}'),
    @('label: "Commands"', 'label: "\u5feb\u6377\u547d\u4ee4"'),
    @('            Drop files to attach', '            {"\u62d6\u653e\u6587\u4ef6\u5230\u6b64\u5904\u6dfb\u52a0"}'),
    @('removeLabel="Remove attachment"', 'removeLabel={"\u79fb\u9664\u9644\u4ef6"}'),
    @('aria-label="Prompt"', 'aria-label={"\u8f93\u5165\u4efb\u52a1"}'),
    @('"Enter shell command..."', '"\u8f93\u5165\u8981\u5728\u5f53\u524d\u5de5\u7a0b\u4e2d\u6267\u884c\u7684\u547d\u4ee4..."'),
    @('"Ask anything, / for commands, @ for context..."', '"\u5206\u6790\u6587\u4ef6\u3001DBC/Trace\uff0c\u6216\u63cf\u8ff0\u6d4b\u8bd5\u4efb\u52a1..."'),
    @('title="Add images and files"', 'title={"\u6dfb\u52a0\u56fe\u7247\u548c\u6587\u4ef6"}'),
    @('attachLabel="Images and files"', 'attachLabel={"\u56fe\u7247\u548c\u6587\u4ef6"}'),
    @('commandsLabel="Commands"', 'commandsLabel={"\u5feb\u6377\u547d\u4ee4"}'),
    @('contextLabel="Context"', 'contextLabel={"\u5de5\u7a0b\u4e0a\u4e0b\u6587"}'),
    @('shellLabel="Shell command"', 'shellLabel={"\u7ec8\u7aef\u547d\u4ee4"}'),
    @('title="Choose agent"', 'title={"\u9009\u62e9\u667a\u80fd\u4f53"}'),
    @('title="Choose model"', 'title={"\u9009\u62e9\u6a21\u578b"}'),
    @('title="Choose model variant"', 'title={"\u9009\u62e9\u601d\u8003\u5f3a\u5ea6"}'),
    @('sendLabel="Send"', 'sendLabel={"\u53d1\u9001"}'),
    @('stopLabel="Stop"', 'stopLabel={"\u505c\u6b62"}')
)
foreach ($replacement in $sessionPromptReplacements) {
    if (-not $sessionPromptText.Contains($replacement[0])) {
        throw "The locked OpenCode prompt UI anchor was not found: $($replacement[0])"
    }
$sessionPromptText = $sessionPromptText.Replace($replacement[0], $replacement[1])
}
[IO.File]::WriteAllText($sessionPrompt, $sessionPromptText, [Text.UTF8Encoding]::new($false))

$sessionTitle = Join-Path $buildRoot "packages\app\src\utils\session-title.ts"
$sessionTitleText = [IO.File]::ReadAllText($sessionTitle)
$sessionTitleImport = 'import { coreTestSessionTitle } from "./coretest-session-title"'
$sessionTitleAnchor = '  return match?.[1] ?? title'
if (-not $sessionTitleText.Contains($sessionTitleAnchor)) {
    throw "The locked OpenCode session title anchor was not found"
}
$sessionTitleText = $sessionTitleImport + "`n`n" + $sessionTitleText
$sessionTitleText = $sessionTitleText.Replace(
    $sessionTitleAnchor,
    '  return coreTestSessionTitle(title)'
)
[IO.File]::WriteAllText($sessionTitle, $sessionTitleText, [Text.UTF8Encoding]::new($false))

$sessionRetry = Join-Path $buildRoot "packages\session-ui\src\components\session-retry.tsx"
$sessionRetryText = [IO.File]::ReadAllText($sessionRetry)
$sessionRetryImport = 'import { Spinner } from "@opencode-ai/ui/spinner"'
if (-not $sessionRetryText.Contains($sessionRetryImport)) {
    throw "The locked OpenCode session retry import anchor was not found"
}
$sessionRetryText = $sessionRetryText.Replace(
    $sessionRetryImport,
    $sessionRetryImport + "`n" + 'import { coreTestProviderRetry } from "@opencode-ai/core/coretest-provider-error"'
)
$sessionRetryMessage = '    if (current.message.length > 80) return current.message.slice(0, 80) + "..."' + "`n" + '    return current.message'
if (-not $sessionRetryText.Contains($sessionRetryMessage)) {
    throw "The locked OpenCode session retry message anchor was not found"
}
$sessionRetryText = $sessionRetryText.Replace(
    $sessionRetryMessage,
    '    const localized = coreTestProviderRetry(current.message)' + "`n" + '    if (localized.length > 80) return localized.slice(0, 80) + "..."' + "`n" + '    return localized'
)
$sessionRetryTruncated = '    return current.message.length > 80'
$sessionRetryTooltip = '<Tooltip value={retry()?.message ?? ""} placement="top">'
if (-not $sessionRetryText.Contains($sessionRetryTruncated) -or -not $sessionRetryText.Contains($sessionRetryTooltip)) {
    throw "The locked OpenCode session retry detail anchors were not found"
}
$sessionRetryText = $sessionRetryText.Replace($sessionRetryTruncated, '    return message().length > 80')
$sessionRetryText = $sessionRetryText.Replace($sessionRetryTooltip, '<Tooltip value={message()} placement="top">')
[IO.File]::WriteAllText($sessionRetry, $sessionRetryText, [Text.UTF8Encoding]::new($false))

$sessionTurn = Join-Path $buildRoot "packages\session-ui\src\components\session-turn.tsx"
$sessionTurnText = [IO.File]::ReadAllText($sessionTurn)
$sessionTurnImport = 'import { Binary } from "@opencode-ai/core/util/binary"'
if (-not $sessionTurnText.Contains($sessionTurnImport)) {
    throw "The locked OpenCode session error import anchor was not found"
}
$sessionTurnText = $sessionTurnText.Replace(
    $sessionTurnImport,
    $sessionTurnImport + "`n" + 'import { coreTestProviderError } from "@opencode-ai/core/coretest-provider-error"'
)
$sessionTurnText = $sessionTurnText.Replace('if (typeof msg === "string") return unwrap(msg)', 'if (typeof msg === "string") return coreTestProviderError(unwrap(msg))')
$sessionTurnText = $sessionTurnText.Replace('return unwrap(String(msg))', 'return coreTestProviderError(unwrap(String(msg)))')
[IO.File]::WriteAllText($sessionTurn, $sessionTurnText, [Text.UTF8Encoding]::new($false))

$timelineRows = Join-Path $buildRoot "packages\app\src\pages\session\timeline\rows.ts"
$timelineRowsText = [IO.File]::ReadAllText($timelineRows)
$timelineRowsImport = 'import { uniqueSummaryDiffs } from "./summary-diffs"'
if (-not $timelineRowsText.Contains($timelineRowsImport)) {
    throw "The locked OpenCode timeline error import anchor was not found"
}
$timelineRowsText = $timelineRowsText.Replace(
    $timelineRowsImport,
    $timelineRowsImport + "`n" + 'import { coreTestProviderError } from "@opencode-ai/core/coretest-provider-error"'
)
$timelineErrorCall = @'
          text: unwrapErrorMessage(
            typeof data === "string" ? data : data === undefined || data === null ? "" : String(data),
          ),
'@
$timelineLocalizedErrorCall = @'
          text: coreTestProviderError(
            unwrapErrorMessage(
              typeof data === "string" ? data : data === undefined || data === null ? "" : String(data),
            ),
          ),
'@
if (-not $timelineRowsText.Contains($timelineErrorCall)) {
    throw "The locked OpenCode timeline error text anchor was not found"
}
$timelineRowsText = $timelineRowsText.Replace($timelineErrorCall, $timelineLocalizedErrorCall)
[IO.File]::WriteAllText($timelineRows, $timelineRowsText, [Text.UTF8Encoding]::new($false))

$messageTimeline = Join-Path $buildRoot "packages\app\src\pages\session\timeline\message-timeline.tsx"
$messageTimelineText = [IO.File]::ReadAllText($messageTimeline)
$errorCard = @'
              <Card variant="error" class="error-card">
                {errorRow().text}
              </Card>
'@
$recoverableErrorCard = @'
              <Card variant="error" class="error-card">
                <div class="flex flex-col items-start gap-2">
                  <span>{errorRow().text}</span>
                  <Show when={props.actions?.revert && sessionID()}>
                    <ButtonV2
                      variant="outline"
                      onClick={() =>
                        void props.actions?.revert?.({
                          sessionID: sessionID()!,
                          messageID: errorRow().userMessageID,
                        })
                      }
                    >
                      {"\u6062\u590d\u4efb\u52a1\u5230\u8f93\u5165\u6846"}
                    </ButtonV2>
                  </Show>
                </div>
              </Card>
'@
if (-not $messageTimelineText.Contains($errorCard)) {
    throw "The locked OpenCode timeline error card anchor was not found"
}
$messageTimelineText = $messageTimelineText.Replace($errorCard, $recoverableErrorCard)
[IO.File]::WriteAllText($messageTimeline, $messageTimelineText, [Text.UTF8Encoding]::new($false))

$titlebar = Join-Path $buildRoot "packages\app\src\components\titlebar.tsx"
$titlebarText = [IO.File]::ReadAllText($titlebar)
if (-not $titlebarText.Contains('<IconV2 name="grid-plus" />')) {
    throw "The locked OpenCode titlebar history icon anchor was not found"
}
if (-not $titlebarText.Contains('icon={<IconV2 name="plus" />}')) {
    throw "The locked OpenCode new session icon anchor was not found"
}
$channelIndicator = '                <ChannelIndicator debugTools={props.debugTools} />'
if (-not $titlebarText.Contains($channelIndicator)) {
    throw "The locked OpenCode channel indicator anchor was not found"
}
$titlebarText = $titlebarText.Replace('<IconV2 name="grid-plus" />', '<IconV2 name="archive" />')
$titlebarText = $titlebarText.Replace('icon={<IconV2 name="plus" />}', 'icon={<IconV2 name="edit" />}')
$titlebarText = $titlebarText.Replace($channelIndicator, '')
[IO.File]::WriteAllText(
    $titlebar,
    $titlebarText,
    [Text.UTF8Encoding]::new($false)
)

$providerTips = @(
    @("en.ts", '"home.providerTip": "Configure model API"'),
    @("zh.ts", '"home.providerTip": "\u914d\u7f6e\u6a21\u578b API"'),
    @("zht.ts", '"home.providerTip": "\u8a2d\u5b9a\u6a21\u578b API"')
)
foreach ($tip in $providerTips) {
    $translation = Join-Path $buildRoot "packages\app\src\i18n\$($tip[0])"
    $translationText = [IO.File]::ReadAllText($translation)
    $providerTipPattern = '(?m)^\s*"home\.providerTip":\s*"[^"]*",\s*$'
    if ([regex]::Matches($translationText, $providerTipPattern).Count -ne 1) {
        throw "The locked OpenCode provider tip key was not found exactly once: $($tip[0])"
    }
    [IO.File]::WriteAllText(
        $translation,
        [regex]::Replace($translationText, $providerTipPattern, "  $($tip[1]),", 1),
        [Text.UTF8Encoding]::new($false)
    )
}

$translationOverrides = @{
    'app.name.desktop' = 'CoreTest Agent'
    'app.server.unreachable' = 'CoreTest Agent \u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528\uff1a{{server}}'
    'app.server.retrying' = '\u6b63\u5728\u81ea\u52a8\u6062\u590d...'
    'app.server.otherServers' = '\u670d\u52a1\u72b6\u6001'
    'command.category.project' = '\u5de5\u7a0b'
    'command.category.provider' = '\u6a21\u578b'
    'command.category.server' = '\u670d\u52a1'
    'command.category.session' = '\u4f1a\u8bdd'
    'command.category.terminal' = '\u7ec8\u7aef'
    'command.project.open' = '\u6253\u5f00\u5de5\u7a0b'
    'command.provider.connect' = '\u914d\u7f6e\u6a21\u578b'
    'command.session.new' = '\u65b0\u5efa\u4f1a\u8bdd'
    'command.terminal.toggle' = '\u7ec8\u7aef'
    'dialog.model.unpaid.freeModels.title' = '\u53ef\u7528\u6a21\u578b'
    'dialog.provider.opencode.note' = '\u4f7f\u7528 CoreTest Agent \u7ba1\u7406\u7684\u6a21\u578b API'
    'dialog.provider.opencode.tagline' = 'CoreTest Agent \u6a21\u578b'
    'dialog.provider.opencodeGo.tagline' = 'CoreTest Agent \u6a21\u578b\u670d\u52a1'
    'dialog.server.title' = '\u670d\u52a1\u72b6\u6001'
    'dialog.server.description' = 'CoreTest Agent \u4f7f\u7528\u672c\u673a\u5185\u7f6e\u670d\u52a1\uff0c\u5ba2\u6237\u65e0\u9700\u914d\u7f6e\u670d\u52a1\u5668\u3002'
    'dialog.server.search.placeholder' = '\u641c\u7d22\u670d\u52a1'
    'dialog.server.empty' = '\u6682\u65e0\u670d\u52a1'
    'dialog.server.add.title' = '\u6dfb\u52a0\u670d\u52a1'
    'dialog.server.add.url' = '\u670d\u52a1\u5730\u5740'
    'dialog.server.add.button' = '\u6dfb\u52a0\u670d\u52a1'
    'dialog.server.edit.title' = '\u7f16\u8f91\u670d\u52a1'
    'dialog.server.default.title' = '\u9ed8\u8ba4\u670d\u52a1'
    'dialog.server.default.description' = 'CoreTest Agent \u4f1a\u968f CoreTest \u81ea\u52a8\u542f\u52a8\uff0c\u4e0d\u9700\u8981\u624b\u52a8\u9009\u62e9\u670d\u52a1\u3002'
    'dialog.server.default.none' = '\u672a\u9009\u62e9\u670d\u52a1'
    'dialog.server.default.set' = '\u8bbe\u4e3a\u9ed8\u8ba4'
    'dialog.server.action.remove' = '\u79fb\u9664\u670d\u52a1'
    'dialog.server.current' = '\u5f53\u524d\u670d\u52a1'
    'dialog.plugins.empty' = '\u5f53\u524d\u6ca1\u6709\u542f\u7528\u63d2\u4ef6'
    'dialog.releaseNotes.action.getStarted' = '\u5f00\u59cb\u4f7f\u7528'
    'dialog.releaseNotes.action.next' = '\u4e0b\u4e00\u6b65'
    'dialog.releaseNotes.action.hideFuture' = '\u4e0d\u518d\u663e\u793a'
    'dialog.releaseNotes.media.alt' = '\u66f4\u65b0\u9884\u89c8'
    'error.chain.checkConfig' = '\u8bf7\u68c0\u67e5\u6a21\u578b API \u914d\u7f6e\u4e2d\u7684 provider/model \u540d\u79f0'
    'error.page.report.prefix' = '\u8bf7\u5c06\u6b64\u9519\u8bef\u53cd\u9988\u7ed9 CoreTest Agent \u652f\u6301\u56e2\u961f'
    'home.empty.title' = '\u6682\u65e0\u5386\u53f2\u4f1a\u8bdd'
    'home.empty.description' = '\u5728\u4e0b\u65b9\u8f93\u5165\u9700\u6c42\uff0cAgent \u4f1a\u57fa\u4e8e\u5f53\u524d CoreTest \u5de5\u7a0b\u5f00\u59cb\u5de5\u4f5c'
    'home.title' = 'CoreTest Agent'
    'home.projects' = '\u5f53\u524d\u5de5\u7a0b'
    'home.project.add' = '\u6dfb\u52a0\u5de5\u7a0b'
    'home.recentProjects' = '\u6700\u8fd1\u5de5\u7a0b'
    'home.recentlyClosed' = '\u6700\u8fd1\u5173\u95ed'
    'home.providerTip' = '\u914d\u7f6e\u6a21\u578b API'
    'prompt.placeholder.normal' = '\u5206\u6790\u6587\u4ef6\u3001DBC/Trace\uff0c\u6216\u63cf\u8ff0\u6d4b\u8bd5\u4efb\u52a1...'
    'prompt.placeholder.simple' = '\u5206\u6790\u6587\u4ef6\u3001DBC/Trace\uff0c\u6216\u63cf\u8ff0\u6d4b\u8bd5\u4efb\u52a1...'
    'prompt.placeholder.shell' = '\u8f93\u5165\u8981\u5728\u5f53\u524d\u5de5\u7a0b\u4e2d\u6267\u884c\u7684\u547d\u4ee4...'
    'prompt.action.attachFile' = '\u6dfb\u52a0\u6587\u4ef6'
    'prompt.menu.addImagesAndFiles' = '\u6dfb\u52a0\u6587\u4ef6\u53ca\u5176\u4ed6\u5185\u5bb9'
    'prompt.menu.imagesAndFiles' = '\u56fe\u7247\u548c\u6587\u4ef6'
    'prompt.menu.commands' = '\u5feb\u6377\u547d\u4ee4'
    'prompt.menu.context' = '\u5de5\u7a0b\u4e0a\u4e0b\u6587'
    'prompt.menu.shellCommand' = '\u7ec8\u7aef\u547d\u4ee4'
    'prompt.attachment.remove' = '\u79fb\u9664\u9644\u4ef6'
    'prompt.action.send' = '\u53d1\u9001'
    'prompt.action.stop' = '\u505c\u6b62'
    'provider.connect.apiKey.description' = '\u8f93\u5165 {{provider}} API Key \u540e\u5373\u53ef\u5728 CoreTest Agent \u4e2d\u4f7f\u7528\u5bf9\u5e94\u6a21\u578b\u3002'
    'provider.connect.oauth.code.visit.suffix' = ' \u83b7\u53d6\u6388\u6743\u7801\uff0c\u5e76\u5728 CoreTest Agent \u4e2d\u8fde\u63a5 {{provider}} \u6a21\u578b\u3002'
    'provider.connect.oauth.auto.visit.suffix' = ' \u5e76\u8f93\u5165\u4ee5\u4e0b\u4ee3\u7801\uff0c\u4ee5\u8fde\u63a5 {{provider}} \u6a21\u578b\u3002'
    'provider.connect.opencodeZen.line1' = 'CoreTest Agent \u4f7f\u7528\u4f60\u914d\u7f6e\u7684 OpenAI-compatible API\u3002'
    'provider.connect.opencodeZen.line2' = '\u53ef\u914d\u7f6e Claude\u3001GPT\u3001Gemini\u3001GLM \u6216\u4f01\u4e1a\u5185\u90e8\u6a21\u578b\u3002'
    'provider.connect.opencodeZen.visit.prefix' = '\u8bf7\u5728 '
    'provider.connect.opencodeZen.visit.link' = '\u6a21\u578b API \u914d\u7f6e'
    'provider.connect.opencodeZen.visit.suffix' = ' \u4e2d\u586b\u5199 Base URL\u3001API Key \u548c\u6a21\u578b\u540d\u3002'
    'settings.general.row.appearance.description' = '\u81ea\u5b9a\u4e49 CoreTest Agent \u7684\u663e\u793a\u6548\u679c'
    'settings.general.row.colorScheme.description' = '\u9009\u62e9 CoreTest Agent \u8ddf\u968f\u7cfb\u7edf\u3001\u6d45\u8272\u6216\u6df1\u8272\u4e3b\u9898'
    'settings.general.row.language.description' = '\u66f4\u6539 CoreTest Agent \u7684\u663e\u793a\u8bed\u8a00'
    'settings.general.row.releaseNotes.description' = '\u66f4\u65b0\u540e\u663e\u793a\u65b0\u529f\u80fd\u5f39\u7a97'
    'settings.general.row.theme.description' = '\u81ea\u5b9a\u4e49 CoreTest Agent \u4e3b\u9898'
    'settings.providers.description' = '\u5728\u8fd9\u91cc\u7ba1\u7406\u6a21\u578b API\u3002'
    'settings.providers.title' = '\u6a21\u578b API'
    'settings.providers.section.connected' = '\u5df2\u914d\u7f6e'
    'settings.providers.connected.empty' = '\u5c1a\u672a\u914d\u7f6e\u6a21\u578b API'
    'sidebar.gettingStarted.title' = '\u5f00\u59cb\u4f7f\u7528'
    'sidebar.gettingStarted.line1' = 'CoreTest Agent \u4f1a\u8bfb\u53d6\u5f53\u524d CoreTest \u5de5\u7a0b\u5e76\u534f\u52a9\u5206\u6790\u3001\u751f\u6210\u548c\u9a8c\u8bc1\u3002'
    'sidebar.gettingStarted.line2' = '\u8bf7\u5148\u914d\u7f6e\u6a21\u578b API\uff0c\u7136\u540e\u76f4\u63a5\u63cf\u8ff0\u4f60\u7684\u6d4b\u8bd5\u6216\u6587\u4ef6\u5206\u6790\u9700\u6c42\u3002'
    'sidebar.nav.projectsAndSessions' = '\u4f1a\u8bdd'
    'sidebar.settings' = '\u8bbe\u7f6e'
    'sidebar.help' = '\u5e2e\u52a9'
    'sidebar.workspaces.enable' = '\u542f\u7528\u5de5\u4f5c\u533a'
    'sidebar.workspaces.disable' = '\u7981\u7528\u5de5\u4f5c\u533a'
    'status.popover.action.manageServers' = '\u670d\u52a1\u72b6\u6001'
    'status.popover.tab.servers' = '\u670d\u52a1'
    'toast.update.description' = 'CoreTest Agent \u6709\u65b0\u7248\u672c ({{version}}) \u53ef\u5b89\u88c5\u3002'
    'wsl.onboarding.step.opencode' = '\u672c\u5730\u8fd0\u884c\u65f6'
    'wsl.onboarding.checkingOpencode' = '\u6b63\u5728\u68c0\u67e5\u672c\u5730\u8fd0\u884c\u65f6...'
    'wsl.onboarding.checkingOpencodeIn' = '\u6b63\u5728\u68c0\u67e5 {{distro}} \u4e2d\u7684\u672c\u5730\u8fd0\u884c\u65f6...'
    'wsl.onboarding.updatingOpencode' = '\u6b63\u5728\u66f4\u65b0\u672c\u5730\u8fd0\u884c\u65f6...'
    'wsl.onboarding.updatingOpencodeIn' = '\u6b63\u5728\u66f4\u65b0 {{distro}} \u4e2d\u7684\u672c\u5730\u8fd0\u884c\u65f6...'
    'wsl.onboarding.updateOpencodeIn' = '\u66f4\u65b0 {{distro}} \u4e2d\u7684\u672c\u5730\u8fd0\u884c\u65f6\u3002'
    'wsl.onboarding.updateOpencode' = '\u66f4\u65b0\u672c\u5730\u8fd0\u884c\u65f6'
    'wsl.onboarding.opencodeReadyIn' = '{{distro}} \u4e2d\u7684\u672c\u5730\u8fd0\u884c\u65f6\u5df2\u5c31\u7eea\u3002'
    'wsl.onboarding.opencodeReady' = '\u672c\u5730\u8fd0\u884c\u65f6\u5df2\u5c31\u7eea\u3002'
    'wsl.onboarding.installOpencodeIn' = '\u5728 {{distro}} \u4e2d\u5b89\u88c5\u672c\u5730\u8fd0\u884c\u65f6\u3002'
    'wsl.onboarding.installOpencode' = '\u5b89\u88c5\u672c\u5730\u8fd0\u884c\u65f6'
    'wsl.onboarding.distroStatus.opencodeMissing' = '\u672a\u5b89\u88c5\u672c\u5730\u8fd0\u884c\u65f6'
    'wsl.onboarding.wslNotInstalled.description' = 'CoreTest Agent \u9700\u8981 WSL\uff08Windows Subsystem for Linux\uff09\u624d\u80fd\u6dfb\u52a0 WSL \u670d\u52a1\u5668'
    'wsl.onboarding.wslUnavailable.description' = 'CoreTest Agent \u65e0\u6cd5\u9a8c\u8bc1\u6b64\u8bbe\u5907\u4e0a\u7684 WSL\u3002'
    'wsl.onboarding.windowsRestartRequired' = '\u91cd\u542f Windows \u4ee5\u5b8c\u6210 WSL \u5b89\u88c5\uff0c\u7136\u540e\u91cd\u65b0\u6253\u5f00 CoreTest Agent\u3002'
    'settings.desktop.wsl.description' = '\u5728 Windows WSL \u4e2d\u8fd0\u884c CoreTest Agent \u672c\u5730\u670d\u52a1\u3002'
}

foreach ($translationFile in Get-ChildItem -LiteralPath (Join-Path $buildRoot "packages\app\src\i18n") -Filter "*.ts") {
    $translation = $translationFile.FullName
    $translationText = [IO.File]::ReadAllText($translation)
    foreach ($key in $translationOverrides.Keys) {
        $escapedKey = [regex]::Escape($key)
        $escapedValue = $translationOverrides[$key].Replace('"', '\"')
        $pattern = "(?ms)^\s*`"$escapedKey`":\s*(?:(?:`"[^`"]*`")|(?:'[^']*')|(?:`"[^`"]*`"\s*\+\s*)+`"[^`"]*`"),\s*$"
        if ([regex]::Matches($translationText, $pattern).Count -eq 1) {
            $translationText = [regex]::Replace($translationText, $pattern, "  `"$key`": `"$escapedValue`",", 1)
        }
    }
    [IO.File]::WriteAllText($translation, $translationText, [Text.UTF8Encoding]::new($false))
}

$uiTranslationOverrides = @{
    'dialog.usageExceeded.freeTier.title' = '\u6a21\u578b\u989d\u5ea6\u4e0d\u53ef\u7528'
    'dialog.usageExceeded.freeTier.description' = '\u5f53\u524d\u6a21\u578b API \u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u5207\u6362\u6a21\u578b\u6216\u68c0\u67e5 API \u914d\u7f6e\u3002'
    'dialog.usageExceeded.freeTier.actionLabel' = '\u6253\u5f00\u8bbe\u7f6e'
    'dialog.usageExceeded.accountRateLimit.title' = '\u6a21\u578b\u989d\u5ea6\u5df2\u7528\u5b8c'
    'dialog.usageExceeded.accountRateLimit.description' = '\u5f53\u524d\u6a21\u578b\u8fd4\u56de\u989d\u5ea6\u9650\u5236\uff0c\u8bf7\u5207\u6362\u6a21\u578b\u6216\u8054\u7cfb\u7ba1\u7406\u5458\u5904\u7406\u3002'
    'dialog.usageExceeded.accountRateLimit.actionLabel' = '\u6253\u5f00\u8bbe\u7f6e'
    'ui.sessionTurn.error.freeUsageExceeded' = '\u6a21\u578b\u989d\u5ea6\u4e0d\u53ef\u7528'
    'ui.sessionTurn.error.addCredits' = '\u6253\u5f00\u8bbe\u7f6e'
}

foreach ($translationFile in Get-ChildItem -LiteralPath (Join-Path $buildRoot "packages\ui\src\i18n") -Filter "*.ts") {
    $translation = $translationFile.FullName
    $translationText = [IO.File]::ReadAllText($translation)
    foreach ($key in $uiTranslationOverrides.Keys) {
        $escapedKey = [regex]::Escape($key)
        $escapedValue = $uiTranslationOverrides[$key].Replace('"', '\"')
        $pattern = "(?ms)^\s*`"$escapedKey`":\s*(?:(?:`"[^`"]*`")|(?:'[^']*')|(?:`"[^`"]*`"\s*\+\s*)+`"[^`"]*`"),\s*$"
        if ([regex]::Matches($translationText, $pattern).Count -eq 1) {
            $translationText = [regex]::Replace($translationText, $pattern, "  `"$key`": `"$escapedValue`",", 1)
        }
    }
    [IO.File]::WriteAllText($translation, $translationText, [Text.UTF8Encoding]::new($false))
}

$wslSettingsModel = Join-Path $buildRoot "packages\app\src\wsl\settings-model.ts"
$wslSettingsModelText = [IO.File]::ReadAllText($wslSettingsModel)
$wslSettingsModelText = $wslSettingsModelText.Replace('return "Install OpenCode"', 'return "Install local runtime"')
$wslSettingsModelText = $wslSettingsModelText.Replace('return "Update OpenCode"', 'return "Update local runtime"')
[IO.File]::WriteAllText($wslSettingsModel, $wslSettingsModelText, [Text.UTF8Encoding]::new($false))

$connectProvider = Join-Path $buildRoot "packages\app\src\components\dialog-connect-provider.tsx"
$connectProviderText = [IO.File]::ReadAllText($connectProvider)
$connectProviderText = $connectProviderText.Replace('href="https://opencode.ai/zen"', 'href="#"')
[IO.File]::WriteAllText($connectProvider, $connectProviderText, [Text.UTF8Encoding]::new($false))

$appPackagePath = Join-Path $buildRoot "packages\app\package.json"
$appPackage = Get-Content -Raw -LiteralPath $appPackagePath | ConvertFrom-Json
$appPackage.dependencies.'ghostty-web' = '0.4.0'
[IO.File]::WriteAllText(
    $appPackagePath,
    ($appPackage | ConvertTo-Json -Depth 20),
    [Text.UTF8Encoding]::new($false)
)

Push-Location $buildRoot
try {
    & $Pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "OpenCode UI dependency installation failed" }
    $env:VITE_OPENCODE_CHANNEL = "stable"
    $env:VITE_DISABLE_DEBUG_BAR = "1"
    Push-Location (Join-Path $buildRoot "packages\app")
    try {
        & (Join-Path $buildRoot "packages\app\node_modules\.bin\vite.cmd") build
    }
    finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) { throw "OpenCode UI build failed" }
}
finally {
    Pop-Location
}

$builtDist = Join-Path $buildRoot "packages\app\dist"
foreach ($map in Get-ChildItem -LiteralPath $builtDist -Recurse -Filter "*.map" -File) {
    Remove-Item -LiteralPath $map.FullName -Force
}
foreach ($asset in Get-ChildItem -LiteralPath $builtDist -Recurse -File | Where-Object {
    $_.Extension -in @(".js", ".css", ".html", ".json", ".webmanifest")
}) {
    $assetText = [IO.File]::ReadAllText($asset.FullName)
    $assetText = [regex]::Replace($assetText, '(?m)^\s*//# sourceMappingURL=.*\.map\s*$', '')
    $assetText = [regex]::Replace($assetText, '(?m)^\s*/\*# sourceMappingURL=.*\.map\s*\*/\s*$', '')
    $assetText = $assetText.Replace("https://opencode.ai/desktop-theme.json", "/desktop-theme.json")
    $assetText = $assetText.Replace("https://opencode.ai/docs/providers/#custom-provider", "#")
    $assetText = $assetText.Replace("https://opencode.ai/docs/providers/", "#")
    $assetText = $assetText.Replace("https://opencode.ai/zen", "#")
    $assetText = $assetText.Replace("https://opencode.ai", "#")
    $assetText = $assetText.Replace("opencode.ai", "coretest.local")
    $assetText = $assetText.Replace("opencode.settings.dat", "coretest_agent.settings.dat")
    $assetText = $assetText.Replace("OpenCode", "CoreTest Agent")
    [IO.File]::WriteAllText($asset.FullName, $assetText.TrimEnd() + "`n", [Text.UTF8Encoding]::new($false))
}

if (Test-Path -LiteralPath $outputRoot) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}
Copy-Item -LiteralPath $builtDist -Destination $outputRoot -Recurse
[IO.File]::WriteAllText($buildPointerPath, $buildRoot, [Text.UTF8Encoding]::new($false))
Write-Output "CoreTest Agent OpenCode UI built: $outputRoot"
