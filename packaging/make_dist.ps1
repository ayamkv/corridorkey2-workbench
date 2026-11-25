<#
Builds the studio package from this checkout:

    dist\CorridorKey2 Workbench\
        Setup.bat
        READ ME FIRST.txt
        app\            application source, assets, setup and public docs
        models\         only with -Models: weights shipped inside the package

    powershell -ExecutionPolicy Bypass -File packaging\make_dist.ps1 [-Release] [-Zip] [-Out <dir>]

-Release requires committed inputs and forbids models. ZIPs get a SHA-256 sidecar;
the package contains a per-file manifest. Existing output is never overwritten.

-Models takes a folder with corridorkey_v2.safetensors and foundation_stats.safetensors, or a
CorridorKey 2.0 folder (its weights\ and vfms\ are taken). -Zip also writes a .zip next to the folder.
#>
param(
    [string]$Out = "",
    [string]$Models = "",
    [switch]$Zip,
    [switch]$Release
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'hash-file.ps1')
$Repo = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $Repo 'dist' }
$Out = [IO.Path]::GetFullPath($Out).TrimEnd('\')
$version = [regex]::Match((Get-Content (Join-Path $Repo 'ckapp\__init__.py') -Raw), '__version__ = "([^"]+)"').Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Missing or invalid app version.' }
if ($Release -and $Models) { throw 'Public releases contain no model weights. Omit -Models.' }
$Stage = Join-Path $Out 'CorridorKey2 Workbench'

Push-Location $Repo
try {
    $dirty = git status --porcelain
    if ($Release -and $dirty) { throw 'Commit release inputs before packaging with -Release.' }
    if ($dirty) { Write-Host "Note: packaging uncommitted changes too." -ForegroundColor DarkYellow }
    $revision = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git revision lookup failed' }
    $files = if ($Release) { git ls-files --cached } else { git ls-files --cached --others --exclude-standard }
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
} finally { Pop-Location }
$zipPath = Join-Path $Out "CorridorKey2-Workbench-$version.zip"
foreach ($existing in @($Stage, $zipPath, ($zipPath + '.sha256'))) {
    if (Test-Path -LiteralPath $existing) { throw "Output already exists: $existing. Choose a new -Out directory." }
}
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'app') | Out-Null
foreach ($f in $files) {
    # Publish only the app, installer and end-user documentation. Local state,
    # environments, models, plans and unrelated untracked files never enter a ZIP.
    if ($f -notmatch '^(ckapp/|packaging/|docs/|licenses/|README\.md$|CHANGELOG\.md$|LICENSE$|THIRD_PARTY_NOTICES\.md$|requirements\.txt$|run_app\.bat$)') { continue }
    if ($f -match '(^|/)(\.venv|venv|\.cache|__pycache__|\.env[^/]*)(/|$)|\.(pyc|pem|key|safetensors|pt|pth|npz)$') {
        throw "Refusing unexpected package input: $f"
    }
    $src = Join-Path $Repo $f
    if (-not (Test-Path $src -PathType Leaf)) { continue }       # deleted but not yet committed
    $dst = Join-Path (Join-Path $Stage 'app') $f
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst
}
Copy-Item (Join-Path $PSScriptRoot 'Setup.bat') $Stage
Copy-Item (Join-Path $PSScriptRoot 'INSTALL.txt') (Join-Path $Stage 'READ ME FIRST.txt')
$required = @('Setup.bat', 'READ ME FIRST.txt', 'app\LICENSE', 'app\THIRD_PARTY_NOTICES.md',
              'app\ckapp\__init__.py', 'app\run_app.bat', 'app\requirements.txt', 'app\packaging\setup.ps1')
foreach ($entry in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $Stage $entry) -PathType Leaf)) { throw "Missing package input: $entry" }
}

function Link-Or-Copy([string]$src, [string]$dst) {
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    if ([IO.Path]::GetPathRoot($src) -eq [IO.Path]::GetPathRoot($dst)) {
        try { New-Item -ItemType HardLink -Path $dst -Target $src | Out-Null; return } catch { }
    }
    Copy-Item $src $dst
}

if ($Models) {
    $m = (Resolve-Path $Models).Path
    $ck = if (Test-Path (Join-Path $m 'corridorkey_v2.safetensors')) { $m } else { Join-Path $m 'weights' }
    foreach ($n in 'corridorkey_v2.safetensors', 'foundation_stats.safetensors') {
        if (-not (Test-Path (Join-Path $ck $n))) { throw "$n not found in $Models" }
        Link-Or-Copy (Join-Path $ck $n) (Join-Path $Stage "models\weights\$n")
    }
    $vfms = Join-Path $m 'vfms'
    if (Test-Path $vfms) {
        Get-ChildItem $vfms -Recurse -File | Where-Object {
            $_.FullName -notmatch '\\(__pycache__|\.cache)\\' -and $_.Name -ne '.gitkeep'
        } | ForEach-Object { Link-Or-Copy $_.FullName (Join-Path $Stage ('models\vfms' + $_.FullName.Substring($vfms.Length))) }
    }
}

$manifestFiles = @(Get-ChildItem -LiteralPath $Stage -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{ path=$_.FullName.Substring($Stage.Length + 1).Replace('\', '/'); size=$_.Length;
                sha256=(Get-WorkbenchSha256 $_.FullName) }
})
$manifest = [ordered]@{ version=$version; source_revision=$revision; source_dirty=[bool]$dirty; files=$manifestFiles }
[IO.File]::WriteAllText((Join-Path $Stage 'package-manifest.json'), ($manifest | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
$size = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Built {0} ({1:N2} GB), version {2}" -f $Stage, ($size / 1GB), $version) -ForegroundColor Green
if ($Zip) {
    & tar.exe -a -c -f $zipPath -C $Out 'CorridorKey2 Workbench'      # Windows' bsdtar: zip64 for big weights
    if ($LASTEXITCODE -ne 0) { throw 'zip failed' }
    $hash = Get-WorkbenchSha256 $zipPath
    [IO.File]::WriteAllText(($zipPath + '.sha256'), "$hash  $([IO.Path]::GetFileName($zipPath))`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host ("Zipped {0} ({1:N2} GB)" -f $zipPath, ((Get-Item $zipPath).Length / 1GB)) -ForegroundColor Green
}
