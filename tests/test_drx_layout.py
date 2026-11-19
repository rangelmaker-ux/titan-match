from pathlib import Path

import pytest

from titan_match import drx_layout as L
from titan_match.resolve_bridge import ResolveBridge

TPL = Path(__file__).resolve().parents[1] / "templates"


def _labels(g):
    return {L._get(n, 1): (L._get(n, 6, b"") or b"").decode() for n in g.nos()}


def test_zstd_raw_roundtrip():
    data = bytes(range(256)) * 1200  # > 1 bloco
    assert L.zstd_read(L.zstd_raw(data)) == data
    assert L.zstd_read(L.zstd_raw(b"")) == b""


def test_protobuf_roundtrip_templates():
    for p in TPL.glob("*.drx"):
        g, _ = L.ler(p.read_text(encoding="utf-8"))
        assert L.parse(L.dump(g.grafo)) == g.grafo


@pytest.mark.parametrize("name", ["TitanMatch_cinema.drx", "TitanMatch_Template.drx"])
def test_templates_em_fileiras_de_4(name):
    g, _ = L.ler((TPL / name).read_text(encoding="utf-8"))
    ordem, pos = L.ordem_e_posicoes(g)
    nos = {L._get(n, 1): (L._get(n, 4), L._get(n, 5)) for n in g.nos()}
    assert nos == pos  # o arquivo já está organizado
    serie = ordem[: len(ordem) if name == "TitanMatch_Template.drx" else 11]
    linhas = {}
    for k in serie:
        linhas.setdefault(pos[k][1], []).append(k)
    assert all(len(v) <= 4 for v in linhas.values())
    assert len(set(pos.values())) == len(pos)  # ninguém em cima de ninguém


def test_cinema_paralelo_na_frente():
    g, _ = L.ler((TPL / "TitanMatch_cinema.drx").read_text(encoding="utf-8"))
    ordem, pos = L.ordem_e_posicoes(g)
    lab = _labels(g)
    by = {lab[k]: pos[k] for k in ordem}
    grade_x = max(by[n][0] for n in ("01 - Input CST", "SKIN - Pele", "07 - Color Balance"))
    xs = {by[n][0] for n in ("GLOW", "HALATION", "GRAIN")}
    assert len(xs) == 1 and xs.pop() > grade_x
    assert by["HALATION"][1] == by["10 - Output CST"][1]  # paralelo centrado na saída
    assert by["10 - Output CST"][0] > by["GLOW"][0]


def test_quadros_montam_no_por_no():
    xml = (TPL / "TitanMatch_cinema.drx").read_text(encoding="utf-8")
    frames = L.quadros(xml)
    g, _ = L.ler(xml)
    assert len(frames) == len(g.nos()) - 1
    for i, q in enumerate(frames):
        gq, _ = L.ler(q)
        ids = {L._get(n, 1) for n in gq.nos()}
        assert len(ids) == i + 1
        assert sorted(L._get(n, 2) for n in gq.nos()) == list(range(1, i + 2))
        assert all(a in ids and b in ids for a, b, _ in gq.ligacoes())
        out = L._get(L.parse(L._get(L.parse(L._get(gq.grafo, 10)), 3)), 4)
        assert out in ids


class _G:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def ApplyGradeFromDRX(self, path, mode):
        self.calls.append(Path(path).read_text(encoding="utf-8"))
        return len(self.calls) != self.fail_at


def test_animacao_nao_bloqueia_quando_falha():
    g = _G(fail_at=3)
    n = ResolveBridge._animate_tree(g, TPL / "TitanMatch_cinema.drx", delay=0)
    assert n == 2 and len(g.calls) == 3


def test_animacao_ignora_template_estranho(tmp_path):
    bad = tmp_path / "x.drx"
    bad.write_text("<xml/>", encoding="utf-8")
    assert ResolveBridge._animate_tree(_G(), bad, delay=0) == 0
