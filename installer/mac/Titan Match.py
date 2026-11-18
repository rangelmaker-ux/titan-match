# Titan Match - abre a interface (Workspace > Scripts > Color > Titan Match), macOS.
# Gerado pelo instalador: o marcador de ROOT abaixo vira a pasta instalada.
import os
import subprocess

ROOT = r"__TITAN_MATCH_ROOT__"
PY = os.path.join(ROOT, "python", "bin", "python3")
APP = os.path.join(ROOT, "app")
if os.path.exists(PY):
    env = dict(os.environ, PYTHONPATH=APP, PYTHONNOUSERSITE="1")
    subprocess.Popen([PY, "-m", "titan_match", "ui"], cwd=APP, env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
else:
    print("Titan Match nao encontrado em: " + ROOT + " (rode o instalador)")
