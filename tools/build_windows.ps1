# Monta o instalador Windows do Titan Match com Python embutido.
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
# Saída: dist\Titan-Match-Windows-<versão>.zip
$ErrorActionPreference = 'Stop'
$repo  = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repo '.venv\Scripts\python.exe'
$ver   = (& $venvPy -c "import sys; sys.path.insert(0, r'$repo\src'); import titan_match; print(titan_match.__version__)").Trim()
$base  = (& $venvPy -c "import sys; print(sys.base_prefix)").Trim()
$out   = Join-Path $repo 'build\Titan-Match-Windows'
$arq   = Join-Path $out 'Arquivos'
Write-Host "Titan Match $ver | Python base: $base"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $arq | Out-Null

# 1) Python completo (tem Tkinter, que o embeddable não traz), sem testes/docs/pacotes do usuário
$pyDst = Join-Path $arq 'python'
robocopy $base $pyDst /E /NFL /NDL /NJH /NJS /NP /XD "$base\Lib\site-packages" "$base\Lib\test" "$base\Lib\idlelib" `
    "$base\Doc" "$base\Tools" "$base\include" "$base\libs" "$base\Scripts" __pycache__ "$base\Lib\tkinter\test" | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $pyDst 'Lib\site-packages') | Out-Null
# pip temporário só para instalar as dependências
robocopy "$base\Lib\site-packages\pip" (Join-Path $pyDst 'Lib\site-packages\pip') /E /NFL /NDL /NJH /NJS /NP | Out-Null
& (Join-Path $pyDst 'python.exe') -m pip install --no-warn-script-location --disable-pip-version-check -q -r (Join-Path $repo 'requirements.txt')
if ($LASTEXITCODE) { throw 'pip install falhou' }
& (Join-Path $pyDst 'python.exe') -m pip uninstall -y -q pip
Get-ChildItem $pyDst -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Remove-Item (Join-Path $pyDst 'Scripts') -Recurse -Force -ErrorAction SilentlyContinue

# 2) App
$app = Join-Path $arq 'app'
robocopy (Join-Path $repo 'src\titan_match') (Join-Path $app 'titan_match') /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ | Out-Null
robocopy (Join-Path $repo 'templates') (Join-Path $app 'templates') *.drx *.json /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy (Join-Path $repo 'assets') (Join-Path $app 'assets') /NFL /NDL /NJH /NJS /NP /XF _* | Out-Null
Set-Content -Path (Join-Path $app 'VERSION') -Value $ver -Encoding ASCII
Set-Content -Path (Join-Path $app 'INSTALLER_VERSION') -Value $ver -Encoding ASCII

# 3) Instalador (PS1 com BOM: o PowerShell 5.1 precisa para ler acentos)
$win = Join-Path $repo 'installer\windows'
Copy-Item (Join-Path $win 'Titan Match.py') $arq
Copy-Item (Join-Path $win 'Instalar_Windows.bat') $out
Copy-Item (Join-Path $win 'LEIA-ME.txt') $out
$ps = [IO.File]::ReadAllText((Join-Path $win 'Instalar_Titan_Match.ps1'))
[IO.File]::WriteAllText((Join-Path $out 'Instalar_Titan_Match.ps1'), $ps, (New-Object Text.UTF8Encoding $true))

# 4) Teste rápido do Python embutido
& (Join-Path $pyDst 'python.exe') -c "import tkinter, numpy, PIL, cv2; print('deps ok', numpy.__version__, cv2.__version__)"
if ($LASTEXITCODE) { throw 'Python embutido incompleto' }

# 5) ZIP
New-Item -ItemType Directory -Force -Path (Join-Path $repo 'dist') | Out-Null
$zip = Join-Path $repo "dist\Titan-Match-Windows-$ver.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
& $venvPy -c "import shutil,sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2])" $zip $out
if ($LASTEXITCODE) { throw 'falha ao gerar o zip' }
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "OK: $zip ($mb MB)"
