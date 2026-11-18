import numpy as np
import pytest

from titan_match import colorspaces as cs
from titan_match import profiles as pf

colour = pytest.importorskip("colour", reason="colour-science não instalado (só para conferência cruzada)")


def test_di_roundtrip():
    x = np.geomspace(1e-5, 100, 500)
    assert np.allclose(cs.di_decode(cs.di_encode(x)), x, rtol=1e-9)
    assert cs.di_encode(0.18) == pytest.approx(0.336, abs=0.001)


def test_gamut_matrix_rows_preserve_white():
    for g in cs.GAMUTS:
        m = cs.gamut_matrix(g, "DaVinci Wide Gamut")
        assert np.allclose(m @ np.ones(3), np.ones(3), atol=1e-6), g


@pytest.mark.parametrize(
    "fn,colour_name,kwargs",
    [
        (cs.slog3_decode, "S-Log3", {}),
        (cs.vlog_decode, "V-Log", {}),
        (cs.clog3_decode, "Canon Log 3", {}),
        (cs.logc3_decode, "ARRI LogC3", {}),
        (cs.log3g10_decode, "Log3G10", {}),
        (cs.dlog_decode, "D-Log", {}),
        (cs.slog2_decode, "S-Log2", {}),
        (cs.clog_decode, "Canon Log", {}),
        (cs.clog2_decode, "Canon Log 2", {}),
        (cs.flog_decode, "F-Log", {}),
        (cs.flog2_decode, "F-Log2", {}),
        (cs.nlog_decode, "N-Log", {}),
        (cs.logc4_decode, "ARRI LogC4", {}),
        (cs.apple_log_decode, "Apple Log Profile", {}),
        (cs.llog_decode, "L-Log", {}),
        (cs.protune_decode, "Protune", {}),
    ],
)
def test_curves_match_colour_science(fn, colour_name, kwargs):
    y = np.linspace(0.05, 0.95, 50)
    try:
        ref = colour.log_decoding(y, function=colour_name, **kwargs)
    except (KeyError, ValueError) as e:
        pytest.skip(f"colour não tem {colour_name}: {e}")
    assert np.allclose(fn(y), ref, rtol=2e-3, atol=2e-5), colour_name


def test_davinci_intermediate_matches_colour_science():
    y = np.linspace(0.01, 0.95, 50)
    assert np.allclose(cs.di_decode(y), colour.models.oetf_inverse_DaVinciIntermediate(y), rtol=1e-6, atol=1e-9)
    x = np.geomspace(1e-4, 50, 50)
    assert np.allclose(cs.di_encode(x), colour.models.oetf_DaVinciIntermediate(x), rtol=1e-6, atol=1e-9)


def test_bmd_gen5_matches_colour_science():
    y = np.linspace(0.05, 0.95, 50)
    fn = getattr(colour.models, "oetf_inverse_BlackmagicFilmGeneration5", None)
    if fn is None:
        pytest.skip("colour sem Blackmagic Film Gen5")
    assert np.allclose(cs.bmdfilm_gen5_decode(y), fn(y), rtol=2e-3, atol=2e-5)


@pytest.mark.parametrize(
    "ours,colour_name",
    [
        ("DaVinci Wide Gamut", "DaVinci Wide Gamut"),
        ("S-Gamut3.Cine", "S-Gamut3.Cine"),
        ("V-Gamut", "V-Gamut"),
        ("Cinema Gamut", "Cinema Gamut"),
        ("ARRI Wide Gamut 3", "ARRI Wide Gamut 3"),
        ("REDWideGamutRGB", "REDWideGamutRGB"),
        ("Blackmagic Wide Gamut", "Blackmagic Wide Gamut"),
        ("D-Gamut", "DJI D-Gamut"),
        ("S-Gamut3", "S-Gamut3"),
        ("S-Gamut3", "S-Gamut"),
        ("Venice S-Gamut3.Cine", "Venice S-Gamut3.Cine"),
        ("Rec.2020", "ITU-R BT.2020"),
        ("Rec.2020", "F-Gamut"),
        ("Rec.2020", "N-Gamut"),
        ("F-Gamut C", "F-Gamut C"),
        ("ARRI Wide Gamut 4", "ARRI Wide Gamut 4"),
        ("Protune Native", "Protune Native"),
    ],
)
def test_gamut_primaries_match_colour_science(ours, colour_name):
    try:
        space = colour.RGB_COLOURSPACES[colour_name]
    except KeyError:
        pytest.skip(f"colour sem {colour_name}")
    assert np.allclose(np.asarray(cs.GAMUTS[ours]), space.primaries, atol=1e-3)
    assert np.allclose(cs.rgb_to_xyz_matrix(ours), space.matrix_RGB_to_XYZ, atol=2e-3)


def test_lab_matches_colour_science():
    xyz = np.array([[0.2, 0.3, 0.1], [0.9, 1.0, 1.08], [0.01, 0.005, 0.02]])
    w = colour.xy_to_XYZ(np.array(cs.D65))
    ref = colour.XYZ_to_Lab(xyz, illuminant=np.array(cs.D65))
    assert np.allclose(cs.xyz_to_lab(xyz), ref, atol=1e-3)
    assert np.allclose(cs.lab_to_xyz(cs.xyz_to_lab(xyz)), xyz, atol=1e-9)
    assert w is not None


def test_mccamy_cct():
    assert cs.xy_to_cct(*cs.D65) == pytest.approx(6504, abs=30)
    assert cs.xy_to_cct(0.44757, 0.40745) == pytest.approx(2856, abs=30)  # iluminante A
