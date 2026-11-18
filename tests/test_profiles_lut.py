import numpy as np
import pytest

from titan_match import colorspaces as cs
from titan_match import lut
from titan_match import profiles as pf
from synth import encode_with_profile


@pytest.mark.parametrize("key", list(pf.PROFILES))
def test_input_cst_maps_mid_grey_to_di(key):
    grey = np.full((1, 3), 0.18)
    code = encode_with_profile(grey, key)
    assert np.allclose(pf.input_cst(code, pf.get_profile(key)), cs.di_encode(0.18), atol=2e-3), key


def test_output_inverse_roundtrip():
    rng = np.random.default_rng(1)
    disp = rng.uniform(0.02, 0.97, (2000, 3))
    back = pf.output_cst(pf.display_to_working(disp))
    assert np.allclose(back, disp, atol=1e-6)


def test_cube_roundtrip(tmp_path):
    paths = lut.build_cst_luts("sony_slog3", tmp_path)
    size, table = lut.read_cube(paths["input_cst"])
    assert size == lut.LUT_SIZE and table.shape == (size ** 3, 3)
    rng = np.random.default_rng(2)
    x = rng.uniform(0.1, 0.7, (500, 3))
    via_lut = lut.apply_cube(table, size, x)
    direct = np.clip(pf.input_cst(x, pf.get_profile("sony_slog3")), 0, 1)
    assert np.abs(via_lut - direct).max() < 0.01
    text = paths["output_cst"].read_text()
    assert "LUT_3D_SIZE 33" in text
