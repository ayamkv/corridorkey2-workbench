<#
CorridorKey2 Workbench setup (studio build).

Installs everything into the folder that holds Setup.bat:
    app\              this app (shipped in the package)
    CorridorKey2.0\   upstream CorridorKey at a tested commit, its venv, weights\ and vfms\
    tools\            uv, Python 3.12, ffmpeg, download cache
Nothing is installed system-wide except two shortcuts (Desktop and Start menu).
Safe to run again: finished steps are skipped, broken ones are redone.

    Setup.bat                              asks how to get the model weights
    Setup.bat -Weights download            download them (about 5 GB)
    Setup.bat -Weights "\\server\ck2"      use weights you already have (copied, or hard-linked on the same drive)
    Setup.bat -Yes -NoShortcuts            unattended
Written for Windows PowerShell 5.1 (ships with Windows), ASCII only.
#>
param(
    [string]$Root = "",
    [string]$Weights = "",
    [switch]$NoShortcuts,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # Invoke-WebRequest is very slow with its progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---------------------------------------------------------------------------- pinned versions
$UV_VERSION   = '0.12.24'
$UV_SHA256    = '7c38608c8a18ee137d748a1773053b07ec8f3a30fab49aebaa6f4e4efeceb019'
$PYTHON       = '3.12'
$CK_COMMIT    = '485f5e9ab759ead6138cc990776184b59d6ea971'     # upstream CorridorKey 2.0, tested
$UTILS3D      = '83bfa5bda008803f6521ce9547f94023b8afeddd'     # same pin as upstream requirements.txt
$TORCH        = @('torch==2.9.1', 'torchvision==0.24.1')
$TORCH_INDEX  = 'https://download.pytorch.org/whl/cu128'
$FFMPEG_URL   = 'https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
$FFMPEG_SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'

$CK_WEIGHTS = @{ 'corridorkey_v2.safetensors' = 2661698720; 'foundation_stats.safetensors' = 18864 }
$NEEDED = @('weights\corridorkey_v2.safetensors', 'weights\foundation_stats.safetensors',
            'vfms\cradio\C-RADIOv4-SO400M\model.safetensors', 'vfms\cradio\C-RADIOv4-SO400M\config.json',
            'vfms\moge\model.pt', 'vfms\rvm\pretrain_rvm_small16_256_204031069.npz')

# ---------------------------------------------------------------------------- paths
if (-not $Root) { $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$Root  = (Resolve-Path $Root).Path.TrimEnd('\')
$App   = Join-Path $Root 'app'
$Ck    = Join-Path $Root 'CorridorKey2.0'
$Tools = Join-Path $Root 'tools'
$Tmp   = Join-Path $Tools 'tmp'
$Uv    = Join-Path $Tools 'uv\uv.exe'
$CkPy  = Join-Path $Ck '.venv\Scripts\python.exe'
$AppPy = Join-Path $App '.venv\Scripts\python.exe'
$AppPyw = Join-Path $App '.venv\Scripts\pythonw.exe'

# Keep every download, cache and temp file inside the install folder (the system drive may be full).
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools 'python'
$env:UV_CACHE_DIR = Join-Path $Tools 'uv-cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:HF_HOME = Join-Path $Tools 'hf'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:TMP = $Tmp
$env:TEMP = $Tmp

# ---------------------------------------------------------------------------- helpers
function Say([string]$text, [string]$color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Yellow }
function Ok([string]$text) { Write-Host "   [ok] $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "   [!]  $text" -ForegroundColor DarkYellow }
function Fail([string]$text) { throw $text }

function Ask([string]$question, [bool]$default = $true) {
    if ($Yes) { return $default }
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    $a = Read-Host "   $question $hint"
    if (-not $a) { return $default }
    return $a.Trim().ToLower().StartsWith('y')
}

function Run([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { Fail "$([IO.Path]::GetFileName($exe)) failed (exit code $LASTEXITCODE)" }
}

function Works([string]$exe, [string]$code) {
    if (-not (Test-Path $exe)) { return $false }
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe -c $code 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
    finally { $ErrorActionPreference = $old }
}

function Download([string]$url, [string]$dest, [string]$sha256 = '') {
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    $part = "$dest.part"
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 --progress-bar -o $part $url
        if ($LASTEXITCODE -ne 0) { Fail "download failed: $url" }
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $part
    }
    if ($sha256) {
        $got = (Get-FileHash -Algorithm SHA256 $part).Hash.ToLower()
        if ($got -ne $sha256) { Remove-Item $part -Force; Fail "checksum mismatch for $url" }
    }
    Move-Item -Force $part $dest
}

function Free-GB([string]$path) {
    $drive = (Get-Item $path).PSDrive
    if ($drive -and $drive.Free) { return [math]::Round($drive.Free / 1GB, 1) }
    return -1
}

function Missing-Weights { return @($NEEDED | Where-Object { -not (Test-Path (Join-Path $Ck $_)) }) }

function Find-Weights([string]$dir) {
    # A folder with corridorkey_v2.safetensors in it or in weights\, and maybe a vfms\ folder
    # (an existing CorridorKey 2.0 install, or a studio share laid out the same way).
    if (-not $dir -or -not (Test-Path $dir -PathType Container)) { return $null }
    $dir = (Resolve-Path $dir).Path
    foreach ($cand in @($dir, (Join-Path $dir 'weights'))) {
        if (Test-Path (Join-Path $cand 'corridorkey_v2.safetensors')) {
            $vfms = Join-Path $dir 'vfms'
            if (-not (Test-Path $vfms)) { $vfms = '' }
            return @{ Ck = $cand; Vfms = $vfms; Dir = $dir }
        }
    }
    return $null
}

function Same-Volume([string]$a, [string]$b) {
    return ([IO.Path]::GetPathRoot($a).ToLower() -eq [IO.Path]::GetPathRoot($b).ToLower()) -and
           -not $a.StartsWith('\\')
}

function Place-File([string]$src, [string]$dst) {
    if (Test-Path $dst) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    $size = (Get-Item $src).Length
    if (Same-Volume $src $dst) {
        try { New-Item -ItemType HardLink -Path $dst -Target $src | Out-Null; return } catch { }
    }
    if ($size -gt 50MB) { Say ("   copying {0} ({1:N1} GB)" -f [IO.Path]::GetFileName($src), ($size / 1GB)) }
    Copy-Item $src $dst
}

function Place-Tree([string]$src, [string]$dst) {
    $src = (Resolve-Path $src).Path
    Get-ChildItem $src -Recurse -File | Where-Object {
        $_.FullName -notmatch '\\(__pycache__|\.cache)\\' -and $_.Name -ne '.gitkeep'
    } | ForEach-Object { Place-File $_.FullName (Join-Path $dst $_.FullName.Substring($src.Length).TrimStart('\')) }
}

function Pick-Folder {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $d = New-Object System.Windows.Forms.FolderBrowserDialog
        $d.Description = 'Folder with corridorkey_v2.safetensors (or a CorridorKey 2.0 folder with weights and vfms)'
        $d.ShowNewFolderButton = $false
        $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }    # in front of the console
        if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { return $d.SelectedPath }
        return ''
    } catch {
        return (Read-Host '   Folder path').Trim('"', ' ')
    }
}

function Make-Shortcut([string]$lnk, [string]$target, [string]$arguments, [string]$workdir, [string]$icon) {
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $workdir
    $s.IconLocation = $icon
    $s.Description = 'CorridorKey2 Workbench'
    $s.Save()
}

# ============================================================================ run
try { Start-Transcript -Append -Path (Join-Path $Root 'setup.log') | Out-Null } catch { }
try {
    Say ''
    Say 'CorridorKey2 Workbench setup' 'White'
    Say "Installing into $Root"

    # ------------------------------------------------------------------------ checks
    Step 'Checking this PC'
    if (-not (Test-Path (Join-Path $App 'ckapp\__init__.py'))) {
        Fail "app\ckapp is missing. Run Setup.bat from the unzipped CorridorKey2 Workbench folder."
    }
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    if ($Root -match '[^\x20-\x7E]') {
        Warn 'The folder path has non-English characters; ffmpeg or OpenCV may fail to open files there.'
        if (-not (Ask 'Continue anyway?' $false)) { Fail 'Move the folder to a plain path (for example D:\CorridorKey2 Workbench) and run Setup.bat again.' }
    }
    $gpu = $null
    try { $gpu = (& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null | Select-Object -First 1) } catch { }
    if ($gpu) {
        $name, $mem, $drv = $gpu.Split(',') | ForEach-Object { $_.Trim() }
        Ok "$name, $([math]::Round([int]$mem / 1024, 1)) GB, driver $drv"
        if ([int]$mem -lt 3900) { Warn 'CorridorKey needs at least 4 GB of GPU memory.' }
    } else {
        Warn 'No NVIDIA GPU found (nvidia-smi did not answer). CorridorKey needs an NVIDIA RTX 30-series or newer.'
        if (-not (Ask 'Install anyway?' $false)) { Fail 'Setup stopped: no NVIDIA GPU.' }
    }

    # ------------------------------------------------------------------------ weights: decide first, so the rest runs unattended
    Step 'Model weights'
    $source = $null
    $download = $false
    if ((Missing-Weights).Count -eq 0) {
        Ok 'Already in place'
    } elseif ($Weights -eq 'download') {
        $download = $true
    } elseif ($Weights) {
        $source = Find-Weights $Weights
        if (-not $source) { Fail "No corridorkey_v2.safetensors in $Weights (or in its weights folder)." }
    } else {
        $bundled = Find-Weights (Join-Path $Root 'models')
        if ($bundled) {
            Ok "Using the weights that came with this package ($($bundled.Dir))"
            $source = $bundled
        } else {
            Say '   1  Download them (about 5 GB from Hugging Face and Google)'
            Say '   2  I already have them: choose the folder'
            while (-not $source -and -not $download) {
                $c = if ($Yes) { '1' } else { (Read-Host '   Choose 1 or 2').Trim() }
                if ($c -eq '1') { $download = $true }
                elseif ($c -eq '2') {
                    $picked = Pick-Folder
                    $source = Find-Weights $picked
                    if (-not $source) { Warn "No corridorkey_v2.safetensors in '$picked' or its weights folder. Try again." }
                }
            }
        }
    }
    if ($source) {
        Say "   From $($source.Dir)"
        if (-not $source.Vfms) { Say '   (no vfms folder there: the three helper models, about 2.4 GB, will be downloaded)' }
    }

    $free = Free-GB $Root
    $need = 10
    if ($download -or ($source -and -not (Same-Volume $source.Dir $Root))) { $need = 15 }
    if ($free -ge 0) {
        if ($free -lt $need) {
            Warn "$free GB free on this drive; setup needs about $need GB."
            if (-not (Ask 'Continue anyway?' $false)) { Fail 'Setup stopped: not enough disk space.' }
        } else { Ok "$free GB free on this drive" }
    }

    # ------------------------------------------------------------------------ uv + Python
    Step "Python $PYTHON (private copy via uv $UV_VERSION)"
    if (-not (Test-Path $Uv)) {
        $zip = Join-Path $Tmp 'uv.zip'
        Download "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-pc-windows-msvc.zip" $zip $UV_SHA256
        Expand-Archive -Force $zip (Join-Path $Tools 'uv')
        Remove-Item $zip
    }
    Run $Uv @('python', 'install', $PYTHON)
    Ok 'Python ready'

    # ------------------------------------------------------------------------ CorridorKey (upstream)
    Step 'CorridorKey 2.0'
    $stamp = Join-Path $Ck '.workbench-commit'
    $have = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { '' }
    if (-not (Test-Path (Join-Path $Ck 'infer.py')) -or $have -ne $CK_COMMIT) {
        $zip = Join-Path $Tmp 'corridorkey.zip'
        Download "https://github.com/nikopueringer/CorridorKey2.0/archive/$CK_COMMIT.zip" $zip
        $x = Join-Path $Tmp 'ck-src'
        if (Test-Path $x) { Remove-Item -Recurse -Force $x }
        Expand-Archive -Force $zip $x
        $srcDir = (Get-ChildItem $x -Directory | Select-Object -First 1).FullName
        # merge over what is there: keeps .venv, weights and vfms
        & robocopy.exe $srcDir $Ck /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { Fail "could not copy CorridorKey into $Ck" }
        Set-Content -Path $stamp -Value $CK_COMMIT -Encoding ASCII
        Remove-Item -Recurse -Force $x, $zip
    }
    Ok "Code at $($CK_COMMIT.Substring(0, 7))"

    $ckCheck = 'import torch, torchvision, transformers, timm, utils3d, einops, scipy, cv2, safetensors'
    if (-not (Works $CkPy $ckCheck)) {
        Say '   Installing PyTorch (CUDA 12.8) and CorridorKey packages: about 3 GB, a few minutes'
        Run $Uv @('venv', '--clear', '--python', $PYTHON, (Join-Path $Ck '.venv'))
        Run $Uv (@('pip', 'install', '--python', $CkPy) + $TORCH + @('--index-url', $TORCH_INDEX))
        # utils3d comes as a GitHub archive at the same commit, so git doesn't have to be installed
        $req = Join-Path $Tmp 'ck-requirements.txt'
        (Get-Content (Join-Path $Ck 'requirements.txt')) | ForEach-Object {
            if ($_ -match '^\s*utils3d\s*@') { "utils3d @ https://github.com/EasternJournalist/utils3d/archive/$UTILS3D.zip" } else { $_ }
        } | Set-Content -Path $req -Encoding ASCII
        Run $Uv @('pip', 'install', '--python', $CkPy, '-r', $req)
        if (-not (Works $CkPy $ckCheck)) { Fail 'CorridorKey packages did not install correctly; see setup.log.' }
    }
    if (Works $CkPy 'import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)') { Ok 'PyTorch sees the GPU' }
    else { Warn 'PyTorch cannot use the GPU. Update the NVIDIA driver, then run Setup.bat again.' }

    # ------------------------------------------------------------------------ the app
    Step 'CorridorKey2 Workbench app'
    $appCheck = 'import PySide6.QtWidgets, OpenGL.GL, cv2, numpy, fastapi, uvicorn'
    if (-not (Works $AppPy $appCheck)) {
        Run $Uv @('venv', '--clear', '--python', $PYTHON, (Join-Path $App '.venv'))
        Run $Uv @('pip', 'install', '--python', $AppPy, '-r', (Join-Path $App 'requirements.txt'))
        if (-not (Works $AppPy $appCheck)) { Fail 'App packages did not install correctly; see setup.log.' }
    }
    Ok 'App ready'

    # ------------------------------------------------------------------------ ffmpeg
    Step 'ffmpeg'
    $ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
    $ffLocal = Join-Path $Tools 'ffmpeg\bin\ffmpeg.exe'
    if ($ff) { Ok "Using $($ff.Source)" }
    elseif (Test-Path $ffLocal) { Ok "Using $ffLocal" }
    else {
        $zip = Join-Path $Tmp 'ffmpeg.zip'
        Download $FFMPEG_URL $zip $FFMPEG_SHA256
        $x = Join-Path $Tmp 'ffmpeg-x'
        Expand-Archive -Force $zip $x
        $inner = (Get-ChildItem $x -Directory | Select-Object -First 1).FullName
        if (Test-Path (Join-Path $Tools 'ffmpeg')) { Remove-Item -Recurse -Force (Join-Path $Tools 'ffmpeg') }
        Move-Item $inner (Join-Path $Tools 'ffmpeg')
        Remove-Item -Recurse -Force $x, $zip
        Ok "Installed $ffLocal"
    }

    # ------------------------------------------------------------------------ weights: place / download
    Step 'Placing the model weights'
    if ($source) {
        foreach ($n in $CK_WEIGHTS.Keys) {
            $src = Join-Path $source.Ck $n
            if (Test-Path $src) { Place-File $src (Join-Path $Ck "weights\$n") }
        }
        if ($source.Vfms) { Place-Tree $source.Vfms (Join-Path $Ck 'vfms') }
    }
    $missing = Missing-Weights
    if ($missing.Count -gt 0) {
        $args_ = @((Join-Path $Ck 'scripts\download_weights.py'), '--package_root', $Ck)
        if ((Test-Path (Join-Path $Ck 'weights\corridorkey_v2.safetensors')) -and
            (Test-Path (Join-Path $Ck 'weights\foundation_stats.safetensors'))) { $args_ += '--skip_corridorkey' }
        Say "   Downloading: $($missing -join ', ')"
        Run $CkPy $args_
    }
    foreach ($n in $CK_WEIGHTS.Keys) {
        $f = Join-Path $Ck "weights\$n"
        if ((Get-Item $f).Length -ne $CK_WEIGHTS[$n]) { Warn "$n has an unexpected size; it may be damaged. Delete it and run Setup.bat again." }
    }
    if ((Missing-Weights).Count -gt 0) { Fail "Still missing: $((Missing-Weights) -join ', ')" }
    Ok 'All weights in place'

    # ------------------------------------------------------------------------ launchers
    Step 'Shortcuts'
    $icon = Join-Path $App 'ckapp\app\assets\app.ico'
    $launcher = Join-Path $Root 'CorridorKey2 Workbench.bat'
    Set-Content -Path $launcher -Encoding ASCII -Value @(
        '@echo off',
        'rem Starts CorridorKey2 Workbench. Drop clips on this file to import them.',
        'call "%~dp0app\run_app.bat" %*')
    Ok "Launcher: $launcher"
    if (-not $NoShortcuts) {
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'CorridorKey2 Workbench.lnk'
        $desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CorridorKey2 Workbench.lnk'
        foreach ($lnk in @($menu, $desk)) { Make-Shortcut $lnk $AppPyw '-m ckapp' $App $icon }
        Ok 'Desktop and Start menu'
    }

    Step 'Done'
    Say "   CorridorKey2 Workbench is installed in $Root" 'Green'
    Say '   To update: replace the app folder with the new one and run Setup.bat again.'
    if (-not $Yes -and (Ask 'Start it now?' $true)) {
        Start-Process -FilePath $AppPyw -ArgumentList '-m', 'ckapp' -WorkingDirectory $App
    }
    $code = 0
} catch {
    Write-Host ''
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Details are in $(Join-Path $Root 'setup.log'). Fix the problem and run Setup.bat again; finished steps are skipped." -ForegroundColor Red
    $code = 1
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
exit $code
