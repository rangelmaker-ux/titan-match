import numpy as np
import pytest

from titan_match import matching
from titan_match.cdl import CDL
from titan_match.engine import analyze
from titan_match.matching import Matcher, MatchResult, register
from titan_match.nodes import CORRECTION_ROLES, LABELS, NodeCorrection, NODE_ROLES, Provenance
from titan_match.profiles import PROFILES
from titan_match.report import format_dry_run
from synth import make_pair


def PURE(**k):
    return matching.MatchOptions(protect_skin=False, separate_skin=False, template="basico", **k)


def test_plan_is_ten_ordered_single_purpose_nodes():
    log, ref = make_pair()
    plan = analyze(ref, log, "sony_slog3", options=PURE()).plan
    assert [n.label for n in plan.nodes] == [l for _, l, _ in NODE_ROLES]
    assert plan.nodes[0].lut_path and plan.nodes[-1].lut_path
    assert plan.nodes[0].cdl is None and plan.nodes[-1].cdl is None
    # cada nó de correção mexe só nos seus parâmetros
    wb = plan.node("white_balance").cdl
    assert wb.slope == (1, 1, 1) and wb.power == (1, 1, 1) and wb.saturation == 1
    sat = plan.node("saturation").cdl
    assert sat.slope == (1, 1, 1) and sat.offset == (0, 0, 0)
    gamma = plan.node("midtones").cdl
    assert gamma.slope == (1, 1, 1) and gamma.offset == (0, 0, 0)
    for n in plan.nodes:
        if n.cdl is not None and not n.cdl.is_identity():
            assert n.provenance, n.label


@pytest.mark.parametrize("profile", list(PROFILES))
def test_match_improves_histogram_for_every_profile(profile):
    log, ref = make_pair(profile)
    a = analyze(ref, log, profile, options=PURE())
    v = a.plan.verification
    assert v["melhorou"], v
    assert v["hist_dist_display_depois"] < 0.5 * v["hist_dist_display_antes"], v
    # Curvas que saturam abaixo do pico da cena sintética (2,56 linear, ex.: Protune = 1,0)
    # perdem as altas no próprio footage; o residual tolerado é um pouco maior.
    clips = float(PROFILES[profile].decode(np.array(1.0))) < 2.56
    assert np.abs(v["delta_lab_medios_depois"]).max() < (3.5 if clips else 3.0), v


def test_identity_when_reference_equals_footage():
    log, ref = make_pair(look=[])
    plan = analyze(ref, log, "sony_slog3", options=PURE()).plan
    for role in CORRECTION_ROLES:
        c = plan.node(role).cdl
        assert np.allclose(c.slope, 1, atol=0.03), role
        assert np.allclose(c.offset, 0, atol=0.02), role
        assert np.allclose(c.power, 1, atol=0.03), role
        assert c.saturation == pytest.approx(1, abs=0.05), role


def test_wrong_comparison_domain_is_not_used():
    """Footage log não é comparado com a referência renderizada: o Input CST vem antes."""
    log, ref = make_pair(look=[])
    a = analyze(ref, log, "sony_slog3", options=PURE())
    # Se comparássemos log x renderizado, o contraste sairia muito diferente de 1.
    assert a.plan.node("exposure_contrast").cdl.slope[0] == pytest.approx(1, abs=0.03)


def test_look_node_flag():
    log, ref = make_pair()
    assert not analyze(ref, log, "sony_slog3", options=PURE()).plan.node("look").enabled
    assert analyze(ref, log, "sony_slog3", options=PURE(film_emulation=True)).plan.node("look").enabled


def test_dry_run_report_lists_every_node_and_source():
    log, ref = make_pair()
    txt = format_dry_run(analyze(ref, log, "sony_slog3", options=PURE()).plan)
    for label in LABELS.values():
        assert label in txt
    assert "medido:" in txt and "DRY-RUN" in txt


def test_matcher_is_pluggable():
    @register
    class Dummy(Matcher):
        name = "dummy_test"

        def match(self, source_working, reference, options):
            cs = {r: NodeCorrection(r) for r in CORRECTION_ROLES}
            cs["saturation"] = NodeCorrection("saturation", CDL(saturation=0.5),
                                              [Provenance("sat", "fixo de teste", {"x": 1})])
            return MatchResult(cs, self.name)

    log, ref = make_pair()
    plan = analyze(ref, log, "sony_slog3", matcher_name="dummy_test", options=PURE()).plan
    assert plan.matcher == "dummy_test"
    assert plan.node("saturation").cdl.saturation == 0.5
    assert "dummy_test" in matching.available_matchers()


def test_matcher_without_provenance_is_rejected():
    res = MatchResult({r: NodeCorrection(r) for r in CORRECTION_ROLES}, "x")
    res.corrections["shadows"] = NodeCorrection("shadows", CDL(offset=(0.1, 0, 0)))
    with pytest.raises(ValueError, match="sem origem"):
        res.validate()
