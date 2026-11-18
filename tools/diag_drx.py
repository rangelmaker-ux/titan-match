"""Testa ApplyGradeFromDRX numa versão de diagnóstico e desfaz tudo no fim."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from titan_match.resolve_bridge import ResolveBridge  # noqa: E402

drx = ROOT / "templates" / "TitanMatch_Template.drx"
br = ResolveBridge()
item = br.target_item()
orig = item.GetCurrentVersion()
print("alvo:", item.GetName(), "| versão atual:", orig, "| drx:", drx, drx.exists(), drx.stat().st_size)
name = "Titan DIAG"
print("AddVersion:", item.AddVersion(name, 0))
print("LoadVersionByName:", item.LoadVersionByName(name, 0), item.GetCurrentVersion())
g = item.GetNodeGraph()
print("nós antes:", g.GetNumNodes())
for mode in (0, 1, 2):
    ok = g.ApplyGradeFromDRX(str(drx), mode)
    g = item.GetNodeGraph()
    print(f"ApplyGradeFromDRX(mode={mode}):", ok, "-> nós:", g.GetNumNodes(),
          [g.GetNodeLabel(i) for i in range(1, g.GetNumNodes() + 1)][:3])
    if g.GetNumNodes() > 1:
        break
print("voltando para", orig["versionName"], item.LoadVersionByName(orig["versionName"], orig["versionType"]))
print("apagando versão DIAG:", item.DeleteVersionByName(name, 0))
print("versões:", item.GetVersionNameList(0), "| atual:", item.GetCurrentVersion())
