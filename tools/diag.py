"""Diagnóstico somente leitura do clipe atual no Resolve."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from titan_match.resolve_bridge import ResolveBridge  # noqa: E402

br = ResolveBridge()
r = br.resolve
p = br.project
print("projeto:", p.GetName(), "| página:", r.GetCurrentPage())
tl = br.timeline
print("timeline:", tl.GetName())
try:
    sel = tl.GetSelectedClips() or []
    print("selecionados:", [c.GetName() for c in sel])
except Exception as e:
    print("GetSelectedClips erro:", e)
cur = tl.GetCurrentVideoItem()
print("sob o playhead:", cur.GetName() if cur else None)
item = br.target_item()
print("ALVO:", item.GetName(), "| versão atual:", item.GetCurrentVersion(), "| versões locais:", item.GetVersionNameList(0))
for n in br.inspect(item):
    print(f"  {n.index:3d} {n.label!r:30s} tools={n.tools} lut={n.lut!r}")
