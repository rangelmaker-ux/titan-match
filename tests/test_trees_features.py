"""Árvores (templates), escolha automática, força do match, pele e nós extras."""
import numpy as np
import pytest

from titan_match import colorspaces as cs
from titan_match import features
from titan_match import profiles as pf
from titan_match.cdl import CDL, apply_chain
from titan_match.engine import analyze, choose_template
from titan_match.matching import MatchOptions
from titan_match.templates import BASIC, BUILTIN, CINEMA, Template, TemplateNode, load_templates
from synth import encode_with_profile, known_look, linear_scene, make_pair


def test_builtin_templates_are_valid():
    for t in BUILTIN.values():
        t.validate()
    assert len(CINEMA.nodes) > len(BASIC.nodes)
    assert {"skin", "glow", "halation", "grain", "nr", "haze"} <= set(CINEMA.roles())


def test_cinema_has_mixer_slot_and_plan_skips_it():
    roles = CINEMA.roles()
    assert len(CINEMA.nodes) == 16 and "mixer" in roles
    assert roles.index("haze") == roles.index("saturation") + 1  # HAZE logo depois da Saturação
    assert "skin_key" not in roles  # a chave de pele é feita no próprio nó SKIN (um clique)
    log, ref = make_pair()
    ts = _with_drx("basico", "cinema")
    plan = analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema"), templates=ts).plan
    assert "mixer" not in [n.role for n in plan.nodes] and len(plan.nodes) == 15


def test_template_validation_rejects_bad_manifest():
    bad = Template("x", "x", [TemplateNode("A", "input_cst"), TemplateNode("A", "output_cst")])
    with pytest.raises(ValueError):
        bad.validate()


def _with_drx(*keys):
    ts = {k: Template(t.key, t.title, list(t.nodes)) for k, t in BUILTIN.items()}
    from pathlib import Path
    for k in keys:
        ts[k].drx = Path(__file__)  # qualquer arquivo existente
    return ts


def test_auto_choice_uses_richer_tree_only_when_needed():
    ts = _with_drx("basico", "cinema")
    t, why = choose_template(ts, "auto", {"skin": False, "nr": False, "glow": False, "halation": False, "grain": False})
    assert t.key == "basico" and "básica" in why
    t, why = choose_template(ts, "auto", {"skin": True, "nr": False, "glow": True, "halation": False, "grain": False})
    assert t.key == "cinema" and "skin" in why
    only_basic = _with_drx("basico")
    t, why = choose_template(only_basic, "auto", {"skin": True, "nr": False, "glow": False, "halation": False,
                                                  "grain": False})
    assert t.key == "basico" and "faltam" in why


def test_strength_scales_toward_identity():
    log, ref = make_pair()
    full = analyze(ref, log, "sony_slog3", options=MatchOptions(template="basico", protect_skin=False,
                                                               separate_skin=False)).plan
    half = analyze(ref, log, "sony_slog3", options=MatchOptions(template="basico", protect_skin=False,
                                                               separate_skin=False, strength=0.5)).plan
    zero = analyze(ref, log, "sony_slog3", options=MatchOptions(template="basico", protect_skin=False,
                                                               separate_skin=False, strength=0.0)).plan
    c_full, c_half = full.node("exposure_contrast").cdl, half.node("exposure_contrast").cdl
    assert c_half.slope[0] == pytest.approx(1 + 0.5 * (c_full.slope[0] - 1), abs=1e-9)
    assert zero.node("saturation").cdl.is_identity()
    assert half.verification["hist_dist_display_depois"] > full.verification["hist_dist_display_depois"]


def _skin_scene():
    """Cena com uma faixa de pele e fundo; referência com look teal forte em tudo."""
    lin = linear_scene(seed=3)
    h, w, _ = lin.shape
    lin[h // 4: h // 2, :] = np.array([0.45, 0.27, 0.18]) * (0.6 + 0.8 * np.linspace(0, 1, w))[None, :, None]
    log = encode_with_profile(lin, "sony_slog3")
    teal = [CDL(offset=(-0.04, 0.0, 0.03)), CDL(saturation=1.2)]
    ref = pf.output_cst(apply_chain(np.clip(cs.di_encode(lin), 0, 1), teal))
    return log, ref, lin


def test_skin_detected_and_protected():
    log, ref, lin = _skin_scene()
    src_w = pf.input_cst(log, pf.get_profile("sony_slog3"))
    mask = features.skin_mask(np.clip(src_w, 0, 1))
    assert mask.mean() > features.SKIN_MIN_FRACTION

    ts = _with_drx("basico", "cinema")
    prot = analyze(ref, log, "sony_slog3", options=MatchOptions(), templates=ts)
    noprot = analyze(ref, log, "sony_slog3", options=MatchOptions(protect_skin=False, template="cinema"),
                     templates=ts)
    assert prot.plan.template_key == "cinema"
    skin = prot.plan.node("skin")
    assert skin.enabled and skin.provenance and not skin.cdl.is_identity()
    assert not noprot.plan.node("skin").enabled

    def skin_hue_err(display):
        w = pf.display_to_working(display)
        lab_res = pf.working_to_lab(np.clip(w, 0, 1)[mask]).mean(axis=0)
        lab_org = pf.working_to_lab(np.clip(src_w, 0, 1)[mask]).mean(axis=0)
        return float(np.hypot(*(lab_res[1:] - lab_org[1:])))

    assert skin_hue_err(prot.after_display) < 0.5 * skin_hue_err(noprot.after_display)


def test_skin_gets_partial_ambience_and_stays_vivid():
    """Pele não fica 100 % na cor do ambiente: fica entre o original e o ambiente, e não perde croma."""
    log, ref, lin = _skin_scene()
    src_w = np.clip(pf.input_cst(log, pf.get_profile("sony_slog3")), 0, 1)
    mask = features.skin_mask(src_w)
    ts = _with_drx("basico", "cinema")

    def skin_lab(display):
        w = np.clip(pf.display_to_working(display), 0, 1)
        return pf.working_to_lab(w[mask]).mean(axis=0)

    lab_orig = pf.working_to_lab(src_w[mask]).mean(axis=0)
    amb = analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema", protect_skin=False), templates=ts)
    lab_amb = skin_lab(amb.after_display)  # pele 100 % no ambiente (sem proteção)
    for a in (0.2, 0.35):
        res = analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema", skin_ambience=a), templates=ts)
        lab = skin_lab(res.after_display)
        d_orig = float(np.hypot(*(lab[1:] - lab_orig[1:])))
        d_amb = float(np.hypot(*(lab[1:] - lab_amb[1:])))
        assert d_amb > 0.2 * float(np.hypot(*(lab_amb[1:] - lab_orig[1:]))), a  # não colou no ambiente
        assert float(np.hypot(*lab[1:])) >= 0.95 * float(np.hypot(*lab_orig[1:])), a  # pele viva
    low = skin_lab(analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema", skin_ambience=0.1),
                           templates=ts).after_display)
    high = skin_lab(analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema", skin_ambience=0.8),
                            templates=ts).after_display)
    # mais ambiência => pele mais perto da cor do ambiente
    assert np.hypot(*(high[1:] - lab_amb[1:])) < np.hypot(*(low[1:] - lab_amb[1:]))


def test_noise_measure_and_nr_decision():
    lin = linear_scene(seed=4)
    clean = np.clip(cs.di_encode(lin), 0, 1)
    rng = np.random.default_rng(0)
    noisy = np.clip(clean + rng.normal(0, 0.02, clean.shape), 0, 1)
    assert features.noise_level(noisy) > 3 * features.noise_level(clean)
    d = features.decide_extras(noisy, clean, pf.output_cst(noisy), pf.output_cst(clean))
    assert d["nr"].enabled and not d["grain"].enabled
    d2 = features.decide_extras(clean, noisy, pf.output_cst(clean), pf.output_cst(noisy))
    assert d2["grain"].enabled and not d2["nr"].enabled


def test_glow_and_halation_detection():
    h, w = 120, 160
    base = np.full((h, w, 3), 0.25)
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(yy - 60, xx - 80)
    sharp = base.copy()
    sharp[r < 10] = 1.0
    glowy = sharp.copy()
    halo = np.clip(1 - (r - 10) / 12, 0, 1)[..., None] * (r >= 10)[..., None]
    glowy = np.clip(glowy + halo * np.array([0.55, 0.25, 0.15]), 0, 1)  # anel avermelhado
    d = features.decide_extras(pf.display_to_working(sharp), pf.display_to_working(glowy), sharp, glowy)
    assert d["glow"].enabled and d["halation"].enabled
    d0 = features.decide_extras(pf.display_to_working(sharp), pf.display_to_working(sharp), sharp, sharp)
    assert not d0["glow"].enabled and not d0["halation"].enabled


def test_progress_callback_reaches_100():
    log, ref = make_pair()
    seen = []
    analyze(ref, log, "sony_slog3", options=MatchOptions(progress=lambda p, m: seen.append(p)))
    assert seen and seen[-1] == 100 and seen == sorted(seen)


def test_toggle_nodes_have_measured_reason():
    log, ref, _ = _skin_scene()
    ts = _with_drx("basico", "cinema")
    plan = analyze(ref, log, "sony_slog3", options=MatchOptions(template="cinema"), templates=ts).plan
    for role in ("nr", "glow", "halation", "grain"):
        n = plan.node(role)
        assert n.provenance and n.provenance[0].formula, role


def test_auto_usa_a_starter_quando_instalada():
    ts = _with_drx("basico", "cinema", "starter")
    t, why = choose_template(ts, "auto", {"skin": True, "nr": False, "glow": True, "halation": False, "grain": False})
    assert t.key == "starter" and "padrão" in why
    t, _ = choose_template(ts, "cinema", {"skin": True})
    assert t.key == "cinema"  # escolher no menu continua valendo
