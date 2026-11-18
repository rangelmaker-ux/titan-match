# Instala o Titan Match: cria .venv, instala dependencias e copia o lancador
# para Workspace > Scripts > Color do DaVinci Resolve. Rode com:
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
if (-not (Test-Path $Venv)) { python -m venv $Venv }
& (Join-Path $Venv "Scripts\python.exe") -m pip install -q -r (Join-Path $Root "requirements.txt")

$Dest = Join-Path $env:APPDATA "Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Color"
New-Item -ItemType Directory -Force $Dest | Out-Null
$Launcher = Get-Content (Join-Path $PSScriptRoot "Titan Match.py") -Raw
$Launcher = $Launcher.Replace("__TITAN_MATCH_ROOT__", $Root)
Set-Content -Path (Join-Path $Dest "Titan Match.py") -Value $Launcher -Encoding utf8
Write-Host "Titan Match instalado. No Resolve: Workspace > Scripts > Color > Titan Match"
