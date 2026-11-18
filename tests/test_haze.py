"""Detecção de neblina/fumaça (dark channel) e decisão do nó HAZE."""
import numpy as np

from titan_match import features
from titan_match import profiles as pf


def _scene(h=160, w=240, seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3))
    img[..., 0] = 0.15 + 0.6 * (x / w)
    img[..., 1] = 0.10 + 0.5 * (y / h)
    img[..., 2] = 0.05 + 0.4 * ((x + y) % 40 < 20)
    img[(x // 20 + y // 20) % 2 == 0] *= 0.15  # regiões escuras (sombras de verdade)
    return np.clip(img + rng.normal(0, 0.01, img.shape), 0, 1)


def _add_haze(img, amount=0.45, airlight=(0.75, 0.78, 0.82)):
    """Modelo físico de névoa: I = J·t + A·(1−t), com t = 1 − amount."""
    t = 1 - amount
    return np.clip(img * t + np.asarray(airlight) * (1 - t), 0, 1)


def test_dark_channel_rises_with_haze():
    clean = _scene()
    hazy = _add_haze(clean)
    m_clean, m_hazy = features.haze_measure(clean), features.haze_measure(hazy)
    assert m_hazy["dark_channel_mediana"] > m_clean["dark_channel_mediana"] + 0.2
    assert m_hazy["contraste_p95_p5"] < m_clean["contraste_p95_p5"]


def test_airlight_color_is_estimated():
    hazy = _add_haze(_scene(), amount=0.6, airlight=(0.55, 0.70, 0.90))  # madrugada azulada
    atm = features.haze_measure(hazy)["luz_atmosferica_rgb"]
    assert atm[2] > atm[0]


def test_haze_node_only_when_reference_is_denser():
    clean = _scene()
    hazy = _add_haze(clean)
    w_clean, w_hazy = pf.display_to_working(clean), pf.display_to_working(hazy)
    d = features.decide_extras(w_clean, w_hazy, clean, hazy)
    assert d["haze"].enabled
    assert 0.2 < d["haze"].measured["densidade_sugerida"] <= 1.0
    d0 = features.decide_extras(w_clean, w_clean, clean, clean)
    assert not d0["haze"].enabled
    d_inv = features.decide_extras(w_hazy, w_clean, hazy, clean)  # footage mais nebuloso que a ref
    assert not d_inv["haze"].enabled


def test_manual_haze_mode_overrides_detection():
    clean = _scene()
    hazy = _add_haze(clean)
    w_clean, w_hazy = pf.display_to_working(clean), pf.display_to_working(hazy)
    assert features.decide_extras(w_clean, w_clean, clean, clean, haze_mode="on")["haze"].enabled
    assert not features.decide_extras(w_clean, w_hazy, clean, hazy, haze_mode="off")["haze"].enabled


def test_white_airlight_is_not_taken_as_fog():
    """Parede/janela estourada (luz da névoa ~branca) não liga o automático."""
    clean = _scene()
    white_veil = _add_haze(clean, amount=0.75, airlight=(1.0, 1.0, 1.0))  # véu branco estourado
    d = features.decide_extras(pf.display_to_working(clean), pf.display_to_working(white_veil), clean, white_veil)
    assert not d["haze"].enabled
