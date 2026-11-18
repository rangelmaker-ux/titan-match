"""Reproduz o fluxo do botão Aplicar (modo Automático) e desfaz no fim."""
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from titan_match.engine import analyze, load_image  # noqa: E402
from titan_match.matching import MatchOptions  # noqa: E402
from titan_match.resolve_bridge import ResolveBridge, check_block  # noqa: E402
from titan_match.templates import load_templates  # noqa: E402
from titan_match.ui import _load_config  # noqa: E402

cfg = _load_config()
print("config:", cfg)
br = ResolveBridge()
item = br.target_item()
orig = item.GetCurrentVersion()
templates = load_templates()
print("templates:", {k: (str(t.drx) if t.drx else None) for k, t in templates.items()})
ref = load_image(cfg["reference"])
src = br.source_frame(item)
a = analyze(ref, src, cfg.get("profile", "sony_slog3"), options=MatchOptions(), templates=templates)
print("árvore:", a.plan.template_key, "|", a.plan.template_reason)
labels = [n.label for n in a.plan.nodes]
chk = check_block(br.inspect(item), labels)
print("check ok:", chk.ok)
tpl = templates.get(a.plan.template_key)
created = None
try:
    rep = br.apply_as_new_version(item, a.plan, tpl.drx, approved=True, reference_display=a.reference_display)
    created = rep.version_created
    print("ok:", rep.ok, "erros:", rep.errors[:5], "| versão:", created)
    for n in br.inspect(item):
        print(f"  {n.index:3d} {n.label!r:30s} tools={n.tools} lut={n.lut!r}")
except Exception:
    traceback.print_exc()
finally:
    cur = item.GetCurrentVersion()
    print("versão atual após aplicar:", cur)
    item.LoadVersionByName(orig["versionName"], orig["versionType"])
    for v in item.GetVersionNameList(0):
        if v not in ("Version 1", orig["versionName"]) and (v == created or v == cur.get("versionName")):
            print("removendo versão de diagnóstico:", v, item.DeleteVersionByName(v, 0))
    print("restaurado:", item.GetCurrentVersion(), item.GetVersionNameList(0))
