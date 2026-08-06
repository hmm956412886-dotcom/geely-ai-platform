param(
    [Parameter(Mandatory = $true)]
    [string]$OpenCodeExecutable,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
} else {
    [System.IO.Path]::GetFullPath($RepoRoot)
}
$executable = [System.IO.Path]::GetFullPath($OpenCodeExecutable)
$lockPath = Join-Path $repoRoot "config\open-source-lock.json"
$licensePath = Join-Path $repoRoot "third_party\OpenCode-MIT.txt"
$noticesPath = Join-Path $repoRoot "third_party\OpenCode-THIRD-PARTY-NOTICES.txt"
$sbomPath = Join-Path $repoRoot "third_party\OpenCode-SBOM.cdx.json"

foreach ($path in ($executable, $lockPath, $licensePath, $noticesPath, $sbomPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required OpenCode delivery artifact is missing: $path"
    }
}

$lock = Get-Content -Raw -LiteralPath $lockPath | ConvertFrom-Json
$asset = $lock.windows_x64_asset
$file = Get-Item -LiteralPath $executable
if ($file.Length -ne [long]$asset.executable_size) {
    throw "OpenCode executable size does not match config/open-source-lock.json"
}
$digest = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne [string]$asset.executable_sha256) {
    throw "OpenCode executable SHA-256 does not match config/open-source-lock.json"
}

$sbom = Get-Content -Raw -LiteralPath $sbomPath | ConvertFrom-Json
if ($sbom.bomFormat -ne "CycloneDX" -or $sbom.specVersion -ne "1.6") {
    throw "OpenCode SBOM must be CycloneDX 1.6"
}
if ($sbom.metadata.component.version -ne [string]$lock.tag.TrimStart("v")) {
    throw "OpenCode SBOM version does not match config/open-source-lock.json"
}
$rootHash = $sbom.metadata.component.hashes |
    Where-Object { $_.alg -eq "SHA-256" } |
    Select-Object -First 1
if ($null -eq $rootHash -or $rootHash.content -ne $digest) {
    throw "OpenCode SBOM executable hash does not match the bundled runtime"
}

$blocked = @($sbom.components | Where-Object {
    $licenseText = ($_.licenses | ConvertTo-Json -Compress)
    $licenseText -match '(?i)UNKNOWN|GPL|AGPL|SSPL|BUSL'
})
if ($blocked.Count -gt 0) {
    throw "OpenCode SBOM contains blocked or unresolved licenses"
}

$notices = Get-Content -Raw -LiteralPath $noticesPath
if ($notices -notmatch "OpenCode v$([regex]::Escape([string]$lock.tag.TrimStart('v')))" -or
    $notices -notmatch [regex]::Escape($digest)) {
    throw "OpenCode third-party Notices do not match the locked runtime"
}

Write-Output "OpenCode $($lock.tag) bundle verified: $executable"
