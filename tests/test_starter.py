"""Árvore Starter (20 nós, espaço para o colorista): template, .drx e match combinado."""
import numpy as np

from synth import make_pair
from titan_match import drx_layout as d
from titan_match.cdl import CDL, apply_cdl, fit_cdl
from titan_match.engine import analyze
from titan_match.matching import MatchOptions
from titan_match.templates import STARTER, TEMPLATES_DIR, load_templates


def test_manifesto_e_drx_batem():
    STARTER.validate()
    t = load_templates()["starter"]
    assert t.drx is not None and t.drx.name == "TitanMatch_starter.drx"
    g, _ = d.ler(t.drx.read_text(encoding="utf-8"))
    nos = g.nos()
    assert len(nos) == 20 == len(STARTER.nodes)
    rot = sorted((d._get(n, 6) or b"").decode() for n in nos)
    assert rot == sorted(n.label for n in STARTER.nodes)
    # Nada do .drx de origem: todo nó rotulado está vazio (mesma correção e nenhum OFX).
    rotulados = [n for n in nos if d._get(n, 6)]
    assert len({d._get(n, 9) for n in rotulados}) == 1
    assert len({d._get(n, 10) for n in rotulados}) == 1
    assert len(d._get(rotulados[0], 10)) < 20


def test_starter_cabe_na_tela_e_anima():
    xml = (TEMPLATES_DIR / "TitanMatch_starter.drx").read_text(encoding="utf-8")
    g, _ = d.ler(xml)
    xs, ys = zip(*(d.xy(n) for n in g.nos()))
    assert max(xs) - min(xs) + d.NODE_W <= 1300 and max(ys) - min(ys) + d.NODE_H <= 700
    assert len(d.quadros(xml)) == 19


def test_fit_cdl_recupera_um_cdl():
    alvo = CDL((1.2, 0.9, 1.05), (0.02, -0.01, 0.0), (0.9, 1.1, 1.0))
    q = np.linspace(0, 1, 200)
    xs = np.stack([q] * 3, axis=1)
    fit, err = fit_cdl(xs, apply_cdl(xs, alvo))
    assert err < 2e-3


def test_starter_combina_as_correcoes_sem_no():
    log, ref = make_pair()
    base = analyze(ref, log, "sony_slog3", options=MatchOptions(template="basico")).plan
    st = analyze(ref, log, "sony_slog3", options=MatchOptions(template="starter")).plan
    assert [n.label for n in st.nodes] == ["CST in", "Exp/bal", "Contrast", "Sat", "CST out", "Sharpening"]
    contrast = st.node("exposure_contrast")
    assert any("Inclui" in n for n in contrast.notes)
    v = st.verification
    assert v["melhorou"]
    # Combinar 5 correções num nó não pode perder muito do match da árvore completa.
    assert v["hist_dist_display_depois"] <= base.verification["hist_dist_display_depois"] * 1.5 + 0.01
