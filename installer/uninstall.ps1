# Removes Omni's program files and shortcuts. Your projects in %USERPROFILE%\.omni stay unless you
# say otherwise, and models downloaded through Ollama stay in Ollama.
$dest = Join-Path $env:LOCALAPPDATA 'Programs\Omni'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
Write-Host 'Removing Omni...'
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$dest*omni.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
foreach ($l in @('Omni.lnk', 'Uninstall Omni.lnk', 'Startup\Omni.lnk')) {
    $p = Join-Path $startMenu $l
    if (Test-Path $p) { Remove-Item $p -Force }
}
$data = Join-Path $env:USERPROFILE '.omni'
if ((Test-Path $data) -and ((Read-Host "Also delete your projects and settings in $data? This cannot be undone. [y/N]") -match '^\s*y')) {
    Remove-Item $data -Recurse -Force
    Write-Host 'Deleted your Omni data.'
}
Write-Host 'Omni is removed. Models stay in Ollama; remove them there if you want the disk space back.'
Set-Location $env:TEMP
Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
Read-Host 'Press Enter to close'
