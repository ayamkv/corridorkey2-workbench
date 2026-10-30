<#
Builds the studio package from this checkout:

    dist\CorridorKey2 Workbench\
        Setup.bat
        READ ME FIRST.txt
        app\            tracked files of this repo (including uncommitted edits)
        models\         only with -Models: weights shipped inside the package

    powershell -ExecutionPolicy Bypass -File packaging\make_dist.ps1 [-Models <folder>] [-Zip] [-Out <dir>]

-Models takes a folder with corridorkey_v2.safetensors and foundation_stats.safetensors, or a
CorridorKey 2.0 folder (its weights\ and vfms\ are taken). -Zip also writes a .zip next to the folder.
#>
param(
    [string]$Out = "",
    [string]$Models = "",
    [switch]$Zip
)
$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $Repo 'dist' }
$version = [regex]::Match((Get-Content (Join-Path $Repo 'ckapp\__init__.py') -Raw), '__version__ = "([^"]+)"').Groups[1].Value
$Stage = Join-Path $Out 'CorridorKey2 Workbench'

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage 'app') | Out-Null

Push-Location $Repo
try {
    $dirty = git status --porcelain
    if ($dirty) { Write-Host "Note: packaging uncommitted changes too." -ForegroundColor DarkYellow }
    $files = git ls-files --cached --others --exclude-standard
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed' }
} finally { Pop-Location }
foreach ($f in $files) {
    if ($f -like 'dist/*') { continue }
    $src = Join-Path $Repo $f
    if (-not (Test-Path $src -PathType Leaf)) { continue }       # deleted but not yet committed
    $dst = Join-Path (Join-Path $Stage 'app') $f
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst
}
Copy-Item (Join-Path $PSScriptRoot 'Setup.bat') $Stage
Copy-Item (Join-Path $PSScriptRoot 'INSTALL.txt') (Join-Path $Stage 'READ ME FIRST.txt')

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

$size = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("Built {0} ({1:N2} GB), version {2}" -f $Stage, ($size / 1GB), $version) -ForegroundColor Green
if ($Zip) {
    $zipPath = Join-Path $Out "CorridorKey2-Workbench-$version.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    & tar.exe -a -c -f $zipPath -C $Out 'CorridorKey2 Workbench'      # Windows' bsdtar: zip64 for big weights
    if ($LASTEXITCODE -ne 0) { throw 'zip failed' }
    Write-Host ("Zipped {0} ({1:N2} GB)" -f $zipPath, ((Get-Item $zipPath).Length / 1GB)) -ForegroundColor Green
}
