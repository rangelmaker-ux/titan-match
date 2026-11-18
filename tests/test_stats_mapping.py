import numpy as np
import pytest

from titan_match import colorspaces as cs
from titan_match import mapping
from titan_match import profiles as pf
from titan_match.cdl import CDL, apply_cdl
from titan_match.stats import compute_stats
from synth import linear_scene

W = np.clip(cs.di_encode(linear_scene()), 0, 1)


def stats_after(c: CDL):
    return compute_stats(apply_cdl(W, c))


def test_zone_fractions():
    s = compute_stats(W)
    assert s.zones["shadows"].pixel_fraction == pytest.approx(0.25, abs=0.01)
    assert s.zones["midtones"].pixel_fraction == pytest.approx(0.50, abs=0.01)
    assert s.zones["highlights"].pixel_fraction == pytest.approx(0.25, abs=0.01)
    assert s.zones["shadows"].luma_mean < s.zones["midtones"].luma_mean < s.zones["highlights"].luma_mean


def test_temperature_and_contrast_measures():
    warm = stats_after(CDL(offset=(0.03, 0, -0.03)))
    cool = stats_after(CDL(offset=(-0.03, 0, 0.03)))
    assert warm.cct_kelvin < cool.cct_kelvin
    flat = stats_after(CDL(slope=(0.8,) * 3, offset=(0.08,) * 3))
    assert flat.contrast_slope < compute_stats(W).contrast_slope


def test_white_balance_maps_to_opposite_offset():
    ref = compute_stats(W)
    cur = stats_after(CDL(offset=(-0.02, 0, 0.03)))  # footage azulado
    c = mapping.map_white_balance(cur, ref)
    r, g, b = c.cdl.offset
    assert r > 0 and b < 0
    assert float(np.dot(c.cdl.offset, pf.DWG_LUMA)) == pytest.approx(0, abs=1e-9)  # luma neutra
    assert c.provenance and all(p.measured for p in c.provenance)


def test_exposure_contrast_recovers_known_transform():
    cur = compute_stats(W)
    ref = stats_after(CDL(slope=(1.2,) * 3, offset=(-0.05,) * 3))
    c = mapping.map_exposure_contrast(cur, ref)
    assert c.cdl.slope[0] == pytest.approx(1.2, abs=0.03)
    out = compute_stats(apply_cdl(W, c.cdl))
    assert out.luma_percentiles[50] == pytest.approx(ref.luma_percentiles[50], abs=0.01)


def test_lift_gamma_gain_move_right_zone():
    cur = compute_stats(W)
    ref_lift = stats_after(CDL(slope=(0.9,) * 3, offset=(0.06,) * 3))
    lift = mapping.map_lift(cur, ref_lift)
    after = compute_stats(apply_cdl(W, lift.cdl))
    assert abs(after.zones["shadows"].luma_mean - ref_lift.zones["shadows"].luma_mean) < \
        abs(cur.zones["shadows"].luma_mean - ref_lift.zones["shadows"].luma_mean)

    ref_gamma = stats_after(CDL(power=(0.85,) * 3))
    gamma = mapping.map_gamma(cur, ref_gamma)
    assert all(p < 1 for p in gamma.cdl.power)

    ref_gain = stats_after(CDL(slope=(1.1,) * 3))
    gain = mapping.map_gain(cur, ref_gain)
    after = compute_stats(apply_cdl(W, gain.cdl))
    assert after.zones["highlights"].luma_mean == pytest.approx(ref_gain.zones["highlights"].luma_mean, abs=0.01)


def test_saturation_bisection_hits_target_chroma():
    cur = compute_stats(W)
    ref = stats_after(CDL(saturation=1.4))
    c = mapping.map_saturation(cur, ref, cur_image=W)
    out = compute_stats(apply_cdl(W, c.cdl))
    assert out.mean_chroma == pytest.approx(ref.mean_chroma, rel=0.02)


def test_clamp_is_recorded():
    cur = compute_stats(W)
    ref = stats_after(CDL(slope=(4.0,) * 3, offset=(-1.0,) * 3))
    c = mapping.map_exposure_contrast(cur, ref)
    assert c.cdl.slope[0] == mapping.LIMITS["contrast_slope"][1]
    assert any("limitado" in n for n in c.notes)
