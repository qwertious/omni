# Omni installer for Windows 10 and 11.
#
# Puts Omni in %LOCALAPPDATA%\Programs\Omni, makes sure Python and Ollama are present (offering to
# install them with winget), adds a Start menu entry and, if you want, starts Omni when you sign in.
# Your projects live in %USERPROFILE%\.omni and are never touched by installing or uninstalling.
# Nothing here needs administrator rights.

param(
    [string]$Dest = '',          # install somewhere else (testing)
    [switch]$Unattended,         # take the default answer to every question
    [switch]$NoShortcuts,        # leave the Start menu alone (testing)
    [switch]$NoLaunch            # do not start Omni at the end (testing)
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src = Join-Path $here 'app'
$dest = if ($Dest) { $Dest } else { Join-Path $env:LOCALAPPDATA 'Programs\Omni' }
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$startup = Join-Path $startMenu 'Startup'

function Say($text) { Write-Host $text }
function Step($text) { Write-Host ''; Write-Host ('== ' + $text) -ForegroundColor White }
function Ask($question, $default = $true) {
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    if ($Unattended) { Write-Host "$question $hint (default)"; return $default }
    $a = Read-Host "$question $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim().ToLower().StartsWith('y')
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

Write-Host ''
Write-Host '  O M N I' -ForegroundColor White
Write-Host '  a workshop of AI makers that runs on this computer'
Write-Host ''

if (-not (Test-Path (Join-Path $src 'omni.py'))) {
    Say "The 'app' folder is missing next to this installer. Unzip the whole download first, then run Install Omni again."
    exit 1
}

# --- Python -----------------------------------------------------------------------------
Step 'Python'
function Find-Python {
    foreach ($c in @(
            @{ exe = 'py'; args = @('-3') },
            @{ exe = 'python'; args = @() },
            @{ exe = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'); args = @() },
            @{ exe = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); args = @() },
            @{ exe = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'); args = @() })) {
        try {
            $out = & $c.exe @($c.args + @('-c', 'import sys;print(sys.version_info[0]*100+sys.version_info[1]);print(sys.executable)')) 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and [int]$out[0] -ge 310 -and $out[1] -notmatch 'WindowsApps') { return $out[1].Trim() }
        } catch { }
    }
    return $null
}
$python = Find-Python
if (-not $python) {
    Say 'Omni needs Python 3.10 or newer, and it is not installed.'
    if ((Have 'winget') -and (Ask 'Install Python 3.12 now with winget (about 30 MB, for your account only)?')) {
        winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $python = Find-Python
    }
    if (-not $python) {
        Say 'Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.'
        exit 1
    }
}
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }
Say "Using $python"

# --- Ollama -----------------------------------------------------------------------------
Step 'Ollama (runs the AI models)'
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not ((Have 'ollama') -or (Test-Path $ollamaExe))) {
    Say 'Ollama is not installed. Omni uses it to run models on this computer.'
    if ((Have 'winget') -and (Ask 'Install Ollama now with winget (about 1 GB)?')) {
        winget install --exact --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        Refresh-Path
    } else {
        Say 'Get it from https://ollama.com/download, install it, then run this again.'
        Start-Process 'https://ollama.com/download'
        exit 1
    }
}
if (Test-Path $ollamaExe) { $ollama = $ollamaExe } else { $ollama = 'ollama' }
try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null } catch {
    Say 'Starting Ollama...'
    $app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path $app) { Start-Process $app } else { Start-Process $ollama -ArgumentList 'serve' -WindowStyle Hidden }
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null; break } catch { }
    }
}

# --- files ------------------------------------------------------------------------------
Step "Copying Omni to $dest"
$running = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$dest*omni.py*" }
foreach ($p in $running) { Say 'Stopping the Omni that is running now...'; Stop-Process -Id $p.ProcessId -Force }
if (Test-Path $dest) {
    Get-ChildItem $dest -Force | Where-Object { $_.Name -ne 'data' } | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item -Path (Join-Path $src '*') -Destination $dest -Recurse -Force
Copy-Item -Path (Join-Path $here 'uninstall.ps1') -Destination $dest -Force

# --- shortcuts ---------------------------------------------------------------------------
Step 'Shortcuts'
if ($NoShortcuts) { Say 'Skipped (-NoShortcuts).' } else {
$shell = New-Object -ComObject WScript.Shell
function Make-Link($path, $target, $arguments, $description) {
    $l = $shell.CreateShortcut($path)
    $l.TargetPath = $target
    $l.Arguments = $arguments
    $l.WorkingDirectory = $dest
    $l.Description = $description
    $icon = Join-Path $dest 'static\omni.ico'
    if (Test-Path $icon) { $l.IconLocation = $icon }
    $l.Save()
}
Make-Link (Join-Path $startMenu 'Omni.lnk') $pythonw "`"$dest\omni.py`"" 'Omni: a workshop of local AI makers'
Make-Link (Join-Path $startMenu 'Uninstall Omni.lnk') 'powershell.exe' "-NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`"" 'Remove Omni'
Say 'Added Omni to the Start menu.'
if (Ask 'Start Omni (in the background) every time you sign in to Windows?') {
    Make-Link (Join-Path $startup 'Omni.lnk') $pythonw "`"$dest\omni.py`" --no-browser" 'Omni in the background'
    Say 'Omni will start when you sign in.'
} elseif (Test-Path (Join-Path $startup 'Omni.lnk')) {
    Remove-Item (Join-Path $startup 'Omni.lnk')
}
}

# --- the small model for comparing ideas ---------------------------------------------------
Step 'Idea comparison model'
Say 'Omni uses a small model (embeddinggemma, about 0.6 GB) to keep new ideas from repeating old ones.'
if (Ask 'Download it now?') {
    & $ollama pull embeddinggemma
}

# --- go ---------------------------------------------------------------------------------
Step 'Done'
Say 'Omni is opening in your browser at http://localhost:7777.'
Say 'Its Models page shows which models suit this computer and downloads them for you.'
if (-not $NoLaunch) { Start-Process $pythonw -ArgumentList "`"$dest\omni.py`"" -WorkingDirectory $dest }
Write-Host ''
