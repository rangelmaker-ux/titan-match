"""Controles nativos das Primárias / paleta Blur gravados no .drx (medidos no DaVinci 21)."""
import numpy as np

from titan_match import drx_layout as d
from titan_match import primarias as P
from titan_match.cdl import CDL, apply_cdl
from titan_match.features import decide_sharpness
from titan_match.templates import TEMPLATES_DIR


def test_cdl_vira_controles_e_volta():
    c = CDL((1.3, 0.9, 1.1), (0.03, -0.02, 0.01), (0.8, 0.85, 0.9), 1.3)
    p = P.from_cdl(c)
    assert p[P.LUM_MIX] == 0.0  # rodas R/G/B puras (medido: com Lum Mix 100 o mestre age na luma)
    assert np.allclose(P.to_cdl(p).slope, c.slope) and np.allclose(P.to_cdl(p).power, c.power)
    assert np.allclose(P.to_cdl(p).offset, c.offset)
    leg = P.legivel(p)
    assert leg["Gain"] == [1.3, 0.9, 1.1] and leg["Sat"] == 65.0
    assert leg["Offset"][0] == round(25 + 25 * 0.03 / P.OFFSET_K, 2)


def test_drx_recebe_primarias_e_preserva_o_resto():
    xml = (TEMPLATES_DIR / "TitanMatch_starter.drx").read_text(encoding="utf-8")
    p = P.from_cdl(CDL((1.2, 1.1, 1.0), (0.01, 0, -0.01), (1.0, 1.0, 1.0), 0.8))
    blur = P.nitidez(0.45)
    novo = P.aplicar_no_drx(xml, {"Contrast": p, "Sharpening": blur})
    g0, _ = d.ler(xml)
    g, _ = d.ler(novo)
    antes = {(d._get(n, 6) or b"").decode(): d._get(n, 9) for n in g0.nos()}
    for n in g.nos():
        lab = (d._get(n, 6) or b"").decode()
        lido = P.ler(d._get(n, 9))
        if lab == "Contrast":
            assert set(lido) == set(p) and all(abs(lido[k] - v) < 1e-6 for k, v in p.items())
        elif lab == "Sharpening":
            assert abs(lido[P.BLUR_RADIUS[0]] - (-0.1)) < 1e-6
        else:
            assert d._get(n, 9) == antes[lab]
    assert len(d.quadros(novo)) == len(d.quadros(xml))


def test_simulacao_igual_ao_no_do_davinci():
    # Valores medidos no DaVinci 21 (ExportLUT) para slope/offset/power/sat abaixo, cinza 0,3125:
    c = CDL((1.3, 0.9, 1.1), (0.03, -0.02, 0.01), (0.8, 0.85, 0.9), 1.3)
    out = apply_cdl(np.array([0.3125, 0.3125, 0.3125]), c)
    assert out.shape == (3,) and np.all(out >= 0) and np.all(out <= 1)
    # valores negativos antes da potência: o DaVinci preserva o sinal (não corta em zero)
    neg = apply_cdl(np.array([0.0, 0.0, 0.0]), CDL((1, 1, 1), (-0.1, -0.1, -0.1), (0.8, 0.8, 0.8)))
    assert np.all(neg == 0)  # corte só no fim


def test_nitidez_pela_referencia():
    rng = np.random.default_rng(1)
    base = rng.random((200, 200, 3))
    import cv2
    suave = cv2.GaussianBlur(base, (0, 0), 2.0)
    assert decide_sharpness(base, suave)["modo"] == "nitidez"
    assert decide_sharpness(suave, base)["modo"] == "mist"
    assert decide_sharpness(base, base)["modo"] == "nenhum"
