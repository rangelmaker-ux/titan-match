"""CST nativo do DaVinci (Color Space Transform v2) nos nós de entrada/saída do .drx."""
import numpy as np
import pytest

from titan_match import cst_ofx
from titan_match import drx_layout as d
from titan_match.engine import analyze, trim_frame
from titan_match.matching import MatchOptions
from titan_match.profiles import PROFILES
from titan_match.templates import TEMPLATES_DIR
from synth import make_pair


def test_todo_perfil_tem_cst_ou_reserva_declarada():
    assert set(cst_ofx.CAMERA) == set(PROFILES)
    assert cst_ofx.CAMERA["sony_slog2"] == ("SGAMUT_COLORSPACE", "SONY_SLOG2_GAMMA")
    assert cst_ofx.CAMERA["gopro_protune"] is None  # sem equivalente no CST: usa o LUT


def test_payload_tem_o_formato_do_davinci():
    p = cst_ofx.params(cst_ofx.input_payload("sony_slog3"))
    assert p["inputColorSpace"] == "SGAMUT3CINE_COLORSPACE" and p["inputGamma"] == "SONY_SLOG3_GAMMA"
    assert p["outputColorSpace"] == "DWG_COLORSPACE" and p["outputGamma"] == "DAV_INTER_OETF_GAMMA"
    assert p["doFwdOOTF"] == 0 and p["doInvOOTF"] == 0 and p["resolvefxVersion"] == "1.4"
    o = cst_ofx.params(cst_ofx.output_payload())
    assert (o["inputColorSpace"], o["outputColorSpace"], o["outputGamma"]) == (
        "DWG_COLORSPACE", "REC709_COLORSPACE", "TWOPOINTFOUR_GAMMA")
    # 564 bytes: o mesmo tamanho que o DaVinci 21 grava para um CST v2 com esses parâmetros
    assert len(cst_ofx.payload("REC709_COLORSPACE", "REC709_APPLE_GAMMA", *cst_ofx.WORKING,
                               inv_ootf=True)) == 564


@pytest.mark.parametrize("arq,ent,sai", [("TitanMatch_starter.drx", "CST in", "CST out"),
                                         ("TitanMatch_cinema.drx", "01 - Input CST", "10 - Output CST")])
def test_drx_recebe_cst_so_nos_nos_de_cst(arq, ent, sai):
    xml = (TEMPLATES_DIR / arq).read_text(encoding="utf-8")
    novo = cst_ofx.aplicar_no_drx(xml, "sony_slog2", {ent}, {sai})
    g0, _ = d.ler(xml)
    g, _ = d.ler(novo)
    antes = {(d._get(n, 6) or b"").decode(): d._get(n, 10) for n in g0.nos()}
    for n in g.nos():
        lab = (d._get(n, 6) or b"").decode()
        p = cst_ofx.params(d._get(n, 10))
        if lab == ent:
            assert p["inputGamma"] == "SONY_SLOG2_GAMMA"
        elif lab == sai:
            assert p["outputGamma"] == "TWOPOINTFOUR_GAMMA"
        else:
            assert d._get(n, 10) == antes[lab]  # o resto do .drx fica igual
    assert len(d.quadros(novo)) == len(d.quadros(xml))  # animação continua funcionando


def test_perfil_sem_cst_mantem_lut():
    xml = (TEMPLATES_DIR / "TitanMatch_starter.drx").read_text(encoding="utf-8")
    assert cst_ofx.aplicar_no_drx(xml, "gopro_protune", {"CST in"}, {"CST out"}) == xml
    log, ref = make_pair("gopro_protune")
    plan = analyze(ref, log, "gopro_protune", options=MatchOptions(template="starter")).plan
    assert plan.node("input_cst").native_cst is None and plan.node("input_cst").lut_path


def test_plano_marca_cst_nativo():
    log, ref = make_pair("sony_slog2")
    plan = analyze(ref, log, "sony_slog2", options=MatchOptions(template="starter")).plan
    assert "SONY_SLOG2_GAMMA" in plan.node("input_cst").native_cst
    assert "Rec.709" in plan.node("output_cst").native_cst


def test_moldura_de_print_sai_e_foto_normal_fica():
    img = np.random.default_rng(0).random((120, 200, 3)) * 0.6 + 0.2
    framed = np.ones((132, 212, 3))
    framed[6:126, 6:206] = img
    assert trim_frame(framed).shape[0] < 120 and trim_frame(framed).min() < 0.9
    blown = img.copy()
    blown[:, -15:] = 1.0  # janela estourada num lado só: é conteúdo, não moldura
    assert trim_frame(blown).shape == blown.shape
    assert trim_frame(img).shape == img.shape


def test_sem_no_de_pele_a_pele_entra_na_conta():
    log, ref = make_pair()
    a = analyze(ref, log, "sony_slog3", options=MatchOptions(template="starter", separate_skin=True))
    assert "sem a pele" not in a.plan.verification["metodo"]
