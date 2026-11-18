# Titan Match - abre a interface (lancador para Workspace > Scripts > Color).
# O install_windows.ps1 copia este arquivo para a pasta de Scripts do Resolve
# e troca o marcador de ROOT abaixo pelo caminho do projeto.
import os
import subprocess

ROOT = r"__TITAN_MATCH_ROOT__"
PY = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
if os.path.exists(PY):
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    subprocess.Popen([PY, "-m", "titan_match", "ui"], cwd=ROOT, env=env,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)
else:
    print("Titan Match nao instalado em: " + ROOT + " (rode scripts/install_windows.ps1)")
