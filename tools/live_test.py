"""Teste de escrita real num PROJETO DE TESTE do Resolve (nunca no projeto do usuário).

Etapas: setup | inspect | template | fill | version | restore
O estado (nome do projeto original etc.) fica em tools/_live_state.json.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from synth import encode_with_profile, known_look, linear_scene  # noqa: E402
from titan_match import colorspaces as cs  # noqa: E402
from titan_match import profiles as pf  # noqa: E402
from titan_match.cdl import apply_chain  # noqa: E402
from titan_match.engine import analyze, load_image  # noqa: E402
from titan_match.report import format_dry_run  # noqa: E402
from titan_match.resolve_bridge import ResolveBridge, check_block  # noqa: E402
from titan_match.stats import compute_stats, histogram_distance  # noqa: E402

WORK = ROOT / "tools" / "_live"
STATE = WORK / "state.json"
TEST_PREFIX = "Titan Match TESTE"


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(**kw):
    s = state(); s.update(kw)
    WORK.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def u8(a):
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def guard_test_project(br):
    name = br.project.GetName()
    if not name.startswith(TEST_PREFIX):
        raise SystemExit(f"ABORTADO: projeto atual '{name}' não é o projeto de teste.")
    return name


def setup(br):
    import datetime
    pm = br.resolve.GetProjectManager()
    orig = pm.GetCurrentProject().GetName()
    save(original_project=orig)
    # Salva o projeto do usuário antes de trocar, para não perder alterações não salvas.
    print("SaveProject (original):", pm.SaveProject())
    WORK.mkdir(parents=True, exist_ok=True)
    lin = linear_scene(540, 960)
    Image.fromarray(u8(encode_with_profile(lin, "sony_slog3"))).save(WORK / "footage_slog3.png")
    ref = pf.output_cst(apply_chain(np.clip(cs.di_encode(lin), 0, 1), known_look()))
    Image.fromarray(u8(ref)).save(WORK / "reference.png")
    name = f"{TEST_PREFIX} {datetime.datetime.now():%Y%m%d-%H%M%S}"
    proj = pm.CreateProject(name)
    if not proj:
        raise SystemExit("CreateProject falhou")
    save(test_project=name)
    mp = proj.GetMediaPool()
    clips = mp.ImportMedia([str(WORK / "footage_slog3.png")])
    if not clips:
        raise SystemExit("ImportMedia falhou")
    tl = mp.CreateTimelineFromClips("Titan Teste", [{"mediaPoolItem": clips[0]}])
    print("original:", orig, "| teste:", pm.GetCurrentProject().GetName(), "| timeline:", bool(tl))
    br.resolve.OpenPage("color")


def inspect(br):
    guard_test_project(br)
    item = br.target_item()
    for n in br.inspect(item):
        print(n)
    print(check_block(br.inspect(item)))


def template(br):
    guard_test_project(br)
    p = br.prepare_template(br.target_item(), WORK / "templates", approved=True)
    save(template=str(p))
    print("drx:", p, p.stat().st_size, "bytes")
    for n in br.inspect(br.target_item()):
        print(n.index, n.label, n.tools)


def _analysis(br, item):
    ref = load_image(WORK / "reference.png")
    src = br.source_frame(item)
    return ref, analyze(ref, src, "sony_slog3")


def _compare(br, item, a, ref):
    graded = br.graded_frame(item)
    sim = a.after_display
    h = min(graded.shape[0], sim.shape[0]); w = min(graded.shape[1], sim.shape[1])
    if graded.shape[:2] != sim.shape[:2]:
        sim = np.asarray(Image.fromarray(u8(sim)).resize(graded.shape[1::-1]), dtype=float) / 255
    diff = np.abs(graded - sim)
    Image.fromarray(u8(graded)).save(WORK / "resolve_graded.png")
    Image.fromarray(u8(sim)).save(WORK / "simulated.png")
    s_g = compute_stats(pf.display_to_working(graded)); s_r = compute_stats(pf.display_to_working(ref))
    s_src = compute_stats(pf.display_to_working(a.neutral_display))
    return {
        "resolve_vs_simulado_mean_abs": round(float(diff.mean()), 4),
        "resolve_vs_simulado_p99_abs": round(float(np.percentile(diff, 99)), 4),
        "hist_ref_vs_resolve": round(histogram_distance(s_g.hist_display, s_r.hist_display), 5),
        "hist_ref_vs_cst_neutro": round(histogram_distance(s_src.hist_display, s_r.hist_display), 5),
    }


def fill(br):
    guard_test_project(br)
    item = br.target_item()
    ref, a = _analysis(br, item)
    print(format_dry_run(a.plan)[-500:])
    before = br.inspect(item)
    rep = br.fill_block(item, a.plan, approved=True, overwrite_titan=True, reference_display=ref)
    print(json.dumps({"ok": rep.ok, "errors": rep.errors, "calls_failed": [c for c in rep.calls if not c["ok"]],
                      "n_calls": len(rep.calls), "verification": rep.verification}, indent=2, ensure_ascii=False))
    for n in br.inspect(item):
        print(n.index, n.label, n.tools, n.lut)
    print("comparacao:", _compare(br, item, a, ref))
    print("nos antes/depois:", len(before), len(br.inspect(item)))


def version(br):
    guard_test_project(br)
    item = br.target_item()
    orig_v = item.GetCurrentVersion()
    ref, a = _analysis(br, item)
    rep = br.apply_as_new_version(item, a.plan, state()["template"], approved=True, reference_display=ref)
    print(json.dumps({"ok": rep.ok, "errors": rep.errors, "version": rep.version_created,
                      "original": orig_v, "verification": rep.verification}, indent=2, ensure_ascii=False))
    for n in br.inspect(item):
        print(n.index, n.label, n.tools, n.lut)
    print("versoes locais:", item.GetVersionNameList(0), "atual:", item.GetCurrentVersion())
    print("comparacao:", _compare(br, item, a, ref))


def open_test(br):
    """Salva o projeto do usuário e abre o projeto de teste já existente."""
    pm = br.resolve.GetProjectManager()
    cur = pm.GetCurrentProject().GetName()
    s = state()
    if not cur.startswith(TEST_PREFIX):
        save(original_project=cur)
        print("SaveProject (original):", cur, pm.SaveProject())
    print("LoadProject:", s["test_project"], bool(pm.LoadProject(s["test_project"])))
    br.resolve.OpenPage("color")


def template_cinema(br):
    from titan_match.templates import CINEMA

    guard_test_project(br)
    p = br.prepare_template(br.target_item(), ROOT / "templates", approved=True, template=CINEMA)
    print("drx:", p, p.stat().st_size, "bytes")
    for n in br.inspect(br.target_item()):
        print(n.index, repr(n.label), n.tools)


def apply_cinema(br):
    from titan_match.matching import MatchOptions
    from titan_match.templates import load_templates

    guard_test_project(br)
    item = br.target_item()
    ts = load_templates()
    ref = load_image(WORK / "reference.png")
    a = analyze(ref, br.source_frame(item), "sony_slog3",
                options=MatchOptions(template="cinema", film_emulation=True), templates=ts)
    print("árvore:", a.plan.template_key, "| ligados:", sum(n.enabled for n in a.plan.nodes), "de", len(a.plan.nodes))
    rep = br.apply_as_new_version(item, a.plan, ts["cinema"].drx, approved=True)
    print("ok:", rep.ok, "| erros:", rep.errors[:5], "| chamadas:", len(rep.calls), "| versão:", rep.version_created)
    for n in br.inspect(item):
        print(f"  {n.index:3d} {n.label!r:28s} tools={n.tools} lut={n.lut!r}")


def person(br):
    """Importa um frame real com pessoa, aplica a árvore Cinema com a referência indicada (argv[2])."""
    from titan_match.matching import MatchOptions
    from titan_match.templates import load_templates

    guard_test_project(br)
    img, ref_path = sys.argv[2], sys.argv[3]
    p = br.project
    mp = p.GetMediaPool()
    clips = mp.ImportMedia([img])
    tl = mp.CreateTimelineFromClips("Titan Pele " + Path(img).stem, [{"mediaPoolItem": clips[0]}])
    p.SetCurrentTimeline(tl)
    item = br.target_item()
    ts = load_templates()
    ref = load_image(ref_path)
    a = analyze(ref, br.source_frame(item), "rec709", options=MatchOptions(template="cinema"), templates=ts)
    sk = a.plan.node("skin")
    print("pele detectada:", a.plan.verification.get("pele_fracao_footage"), "| SKIN ligado:", sk.enabled)
    for pv in sk.provenance:
        print("  ", pv.param, pv.measured)
    rep = br.apply_as_new_version(item, a.plan, ts["cinema"].drx, approved=True)
    print("ok:", rep.ok, rep.errors[:3], "| chamadas:", len(rep.calls), "| pele aguardando clique:", rep.skin_pending)
    Image.fromarray(u8(a.after_display)).save(WORK / "person_sim.png")
    Image.fromarray(u8(a.neutral_display)).save(WORK / "person_neutral.png")


def restore(br):
    pm = br.resolve.GetProjectManager()
    s = state()
    guard_test_project(br)
    pm.SaveProject()
    ok = pm.LoadProject(s["original_project"])
    print("restaurado:", ok, "| atual:", pm.GetCurrentProject().GetName())


if __name__ == "__main__":
    br = ResolveBridge()
    {"setup": setup, "inspect": inspect, "template": template, "fill": fill, "version": version,
     "restore": restore, "open": open_test, "template_cinema": template_cinema,
     "apply_cinema": apply_cinema, "person": person}[sys.argv[1]](br)
