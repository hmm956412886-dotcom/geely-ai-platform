param(
    [string]$Pnpm = "pnpm",
    [string]$Node = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$tmpRoot = Join-Path $repoRoot "tmp"
$buildPointerPath = Join-Path $tmpRoot "opencode-ui-build-current.txt"
$buildRoot = Join-Path $tmpRoot "opencode-ui-build"
if (Test-Path -LiteralPath $buildPointerPath -PathType Leaf) {
    $buildRoot = [IO.Path]::GetFullPath(([IO.File]::ReadAllText($buildPointerPath).Trim()))
}
$distRoot = Join-Path $repoRoot "frontend\opencode-coretest\dist"
$manifestPath = Join-Path $repoRoot "third_party\OpenCode-UI-SOURCE.json"
$sbomPath = Join-Path $repoRoot "third_party\OpenCode-UI-SBOM.cdx.json"
$noticesPath = Join-Path $repoRoot "third_party\OpenCode-UI-THIRD-PARTY-NOTICES.txt"
$assetsPath = Join-Path $repoRoot "third_party\OpenCode-UI-ASSETS.sha256"

if ($Node) {
    $nodePath = [IO.Path]::GetFullPath($Node)
    if (-not (Test-Path -LiteralPath $nodePath -PathType Leaf)) {
        throw "Node executable is missing: $nodePath"
    }
    $env:Path = [IO.Path]::GetDirectoryName($nodePath) + [IO.Path]::PathSeparator + $env:Path
}
foreach ($path in ($buildRoot, $distRoot, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "OpenCode UI compliance input is missing: $path"
    }
}

Push-Location $buildRoot
try {
    $treeJson = (& $Pnpm list --prod --json --depth Infinity) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Could not read the OpenCode UI dependency tree" }
}
finally {
    Pop-Location
}
$parsedRoots = $treeJson | ConvertFrom-Json
$roots = New-Object System.Collections.Generic.List[object]
foreach ($root in $parsedRoots) {
    $roots.Add($root)
}
$source = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$components = @{}
$edges = @{}
$componentPaths = @{}
$visiting = @{}

function Get-LicenseExpression($package) {
    $value = $package.license
    if ($value -is [string] -and $value.Trim()) { return $value.Trim() }
    if ($value.type -is [string] -and $value.type.Trim()) { return $value.type.Trim() }
    return "UNKNOWN"
}

function Get-Repository($package) {
    $value = $package.repository
    if ($value -is [string]) { return $value }
    if ($value.url -is [string]) { return $value.url }
    return ""
}

function Get-Purl([string]$name, [string]$version) {
    if ($name.StartsWith("@") -and $name.Contains("/")) {
        $parts = $name.Split("/", 2)
        return "pkg:npm/$([Uri]::EscapeDataString($parts[0]))/$($parts[1])@$version"
    }
    return "pkg:npm/$name@$version"
}

function Visit-Dependency($node) {
    if ($null -eq $node -or -not $node.path) { return $null }
    $packagePath = Join-Path ([string]$node.path) "package.json"
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { return $null }
    $package = Get-Content -Raw -LiteralPath $packagePath | ConvertFrom-Json
    $name = [string]$package.name
    if (-not $name) { $name = [string]$node.name }
    $version = [string]$package.version
    if (-not $version -and $name.StartsWith("@opencode-ai/")) { $version = "1.18.10" }
    if (-not $version) { return $null }
    $ref = "npm:$name@$version"
    if (-not $components.ContainsKey($ref)) {
        $license = Get-LicenseExpression $package
        $component = [ordered]@{
            type = "library"
            name = $name
            version = $version
            "bom-ref" = $ref
            purl = Get-Purl $name $version
            licenses = @([ordered]@{ expression = $license })
        }
        $repository = Get-Repository $package
        if ($repository) { $component.externalReferences = @([ordered]@{ type = "vcs"; url = $repository }) }
        $components[$ref] = $component
        $componentPaths[$ref] = [string]$node.path
    }
    if ($visiting.ContainsKey($ref)) { return $ref }
    $visiting[$ref] = $true
    $children = New-Object System.Collections.Generic.List[string]
    if ($node.dependencies) {
        foreach ($property in $node.dependencies.PSObject.Properties) {
            $child = Visit-Dependency $property.Value
            if ($child -and -not $children.Contains($child)) { $children.Add($child) }
        }
    }
    $edges[$ref] = @($children | Sort-Object)
    return $ref
}

$rootRefs = New-Object System.Collections.Generic.List[string]
foreach ($root in $roots) {
    if ($root.name -eq "opencode-coretest-ui-workspace") { continue }
    $ref = Visit-Dependency $root
    if ($ref -and -not $rootRefs.Contains($ref)) { $rootRefs.Add($ref) }
}

if ($components.Count -eq 0) {
    throw "OpenCode UI production dependency tree is empty"
}

$blocked = @($components.Values | Where-Object {
    $_.licenses[0].expression -match '(?i)UNKNOWN|GPL|AGPL|SSPL|BUSL'
})
if ($blocked.Count -gt 0) {
    throw "OpenCode UI dependencies contain blocked or unresolved licenses: $($blocked.name -join ', ')"
}

[object[]]$componentList = @(
    foreach ($component in $components.Values) {
        [pscustomobject]$component
    }
) | Sort-Object name, version

$dependencies = New-Object System.Collections.Generic.List[object]
$dependencies.Add([ordered]@{ ref = "coretest-agent-opencode-ui"; dependsOn = @($rootRefs | Sort-Object) })
foreach ($ref in ($edges.Keys | Sort-Object)) {
    $dependencies.Add([ordered]@{ ref = $ref; dependsOn = @($edges[$ref]) })
}
[object[]]$dependencyList = @(
    foreach ($dependency in $dependencies) {
        [pscustomobject]$dependency
    }
)
$sbom = [ordered]@{
    bomFormat = "CycloneDX"
    specVersion = "1.6"
    version = 1
    metadata = [ordered]@{
        component = [ordered]@{
            type = "application"
            name = "CoreTest Agent OpenCode UI"
            version = "1.18.10"
            "bom-ref" = "coretest-agent-opencode-ui"
            licenses = @([ordered]@{ expression = "MIT" })
            externalReferences = @([ordered]@{ type = "vcs"; url = $source.repository })
            properties = @(
                [ordered]@{ name = "opencode:tag"; value = $source.tag },
                [ordered]@{ name = "opencode:commit"; value = $source.commit }
            )
        }
    }
    components = $componentList
    dependencies = $dependencyList
}
[IO.File]::WriteAllText($sbomPath, ($sbom | ConvertTo-Json -Depth 30) + "`n", [Text.UTF8Encoding]::new($false))

$assetLines = Get-ChildItem -LiteralPath $distRoot -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($distRoot.TrimEnd("\").Length + 1).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
[IO.File]::WriteAllLines($assetsPath, $assetLines, [Text.UTF8Encoding]::new($false))

$licenseGroups = @{}
foreach ($ref in ($componentPaths.Keys | Sort-Object)) {
    $packageRoot = $componentPaths[$ref]
    $licenseFiles = @(Get-ChildItem -LiteralPath $packageRoot -File | Where-Object {
        $_.Name -match '^(LICENSE|LICENCE|NOTICE|COPYING)(\..*)?$'
    })
    if ($licenseFiles.Count -eq 0 -and $ref.StartsWith("npm:@opencode-ai/")) {
        $licenseFiles = @(Get-Item -LiteralPath (Join-Path $repoRoot "third_party\OpenCode-MIT.txt"))
    }
    foreach ($file in $licenseFiles) {
        $text = [IO.File]::ReadAllText($file.FullName).Trim()
        if (-not $text) { continue }
        $hashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($text))
        $hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
        if (-not $licenseGroups.ContainsKey($hash)) {
            $licenseGroups[$hash] = [ordered]@{ packages = New-Object System.Collections.Generic.List[string]; text = $text }
        }
        if (-not $licenseGroups[$hash].packages.Contains($ref)) { $licenseGroups[$hash].packages.Add($ref) }
    }
}

$notice = New-Object System.Text.StringBuilder
[void]$notice.AppendLine("CoreTest Agent OpenCode UI Third-Party Notices")
[void]$notice.AppendLine("===============================================")
[void]$notice.AppendLine()
[void]$notice.AppendLine("OpenCode $($source.tag)")
[void]$notice.AppendLine("Source commit: $($source.commit)")
[void]$notice.AppendLine("This UI is built from the locked OpenCode source with the CoreTest Profile in frontend/opencode-coretest.")
[void]$notice.AppendLine()
[void]$notice.AppendLine("Components")
[void]$notice.AppendLine("----------")
foreach ($component in $componentList) {
    [void]$notice.AppendLine("$($component.name)@$($component.version) | $($component.licenses[0].expression)")
}
foreach ($group in ($licenseGroups.Values | Sort-Object { $_.packages[0] })) {
    [void]$notice.AppendLine()
    [void]$notice.AppendLine("Packages: $($group.packages -join ', ')")
    [void]$notice.AppendLine(("-" * 80))
    [void]$notice.AppendLine($group.text)
}
[IO.File]::WriteAllText($noticesPath, $notice.ToString(), [Text.UTF8Encoding]::new($false))

Write-Output "OpenCode UI compliance artifacts generated: $($components.Count) components"
