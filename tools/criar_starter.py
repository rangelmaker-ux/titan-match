"""Gera templates/TitanMatch_starter.drx a partir de um .drx com a estrutura "DR Starter".

Uso:  python tools/criar_starter.py "<caminho do .drx de origem>"

Do arquivo de origem só aproveita o GRAFO: nós, rótulos e ligações. O conteúdo de cada nó volta ao
padrão (sem correção, sem OFX, sem power window, sem sharpening): o plugin preenche os nós dele e
os outros ficam vazios para o colorista. O invólucro (miniatura, metadados) vem do template Cinema,
para não carregar a imagem nem os dados de quem criou o .drx de origem.
Precisa do pacote `zstandard` (o .drx exportado pelo Resolve vem comprimido).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from titan_match import drx_layout as d  # noqa: E402
from titan_match.templates import STARTER  # noqa: E402

GRADE, OFX = 9, 10  # campos do nó: correção do nó / efeitos OFX


def _set(msg: list, field: int, value) -> None:
    for item in msg:
        if item[0] == field:
            item[2] = value
            return
    raise KeyError(field)


def limpar(g: d.Grafo) -> list[str]:
    nos = g.nos()
    rotulos = [(d._get(n, 6) or b"").decode() for n in nos]
    # Payload "vazio" de referência: o de um nó corretivo sem nada (o mais comum no próprio arquivo).
    from collections import Counter

    vazios = [n for n in nos if d._get(n, 6)]
    grade0 = Counter(d._get(n, GRADE) for n in vazios).most_common(1)[0][0]
    ofx0 = Counter(d._get(n, OFX) for n in vazios).most_common(1)[0][0]
    novos = []
    for n in nos:
        if d._get(n, 6):  # mixers (sem rótulo) ficam como estão
            _set(n, GRADE, grade0)
            _set(n, OFX, ofx0)
        novos.append(d.dump(n))
    it = iter(novos)
    g.grafo = [[f, t, next(it) if f == 7 else v] for f, t, v in g.grafo]
    return rotulos


# Layout em duas faixas para caber numa tela de notebook (em linha reta seriam ~1.900 px de largura).
# Faixa de cima: correção primária e objetos. Faixa de baixo: Global, ajustes/power windows em duas
# colunas, look e saída. (x, y) em unidades do editor de nós; depois é centralizado na vista.
LAYOUT = {
    "CST in": (0, 0), "Exp/bal": (150, 0), "Contrast": (300, 0), "Sat": (450, 0),
    "background": (600, -100), "2nd obj": (600, 0), "Main obj": (600, 100), "mixer1": (750, 0),
    "Global": (0, 340),
    "ADJ 1": (150, 240), "ADJ 2": (150, 340), "ADJ 3": (150, 440),
    "PW 1": (300, 240), "PW 2": (300, 340), "PW 3": (300, 440), "mixer2": (450, 340),
    "Final look": (600, 340), "Fine Tune": (750, 340), "CST out": (900, 340), "Sharpening": (1050, 340),
}


def posicionar(g: d.Grafo) -> None:
    nos = g.nos()
    ids = {}
    mixers = sorted((d._get(n, 2), d._get(n, 1)) for n in nos if not d._get(n, 6))
    for i, (_, k) in enumerate(mixers, start=1):
        ids[k] = f"mixer{i}"
    for n in nos:
        if d._get(n, 6):
            ids[d._get(n, 1)] = d._get(n, 6).decode()
    pos = d._centralizar({k: LAYOUT[nome] for k, nome in ids.items()})
    novos = []
    for n in nos:
        x, y = pos[d._get(n, 1)]
        d._set(n, 4, d.zz_enc(x))
        d._set(n, 5, d.zz_enc(y))
        novos.append(d.dump(n))
    it = iter(novos)
    g.grafo = [[f, t, next(it) if f == 7 else v] for f, t, v in g.grafo]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    g, _ = d.ler(Path(argv[0]).read_text(encoding="utf-8"))
    rotulos = limpar(g)
    esperado = sorted(n.label for n in STARTER.nodes if n.label)
    if sorted(r for r in rotulos if r) != esperado:
        raise SystemExit(f"Rótulos diferentes do manifesto Starter: {sorted(rotulos)}")
    base = (ROOT / "templates" / "TitanMatch_cinema.drx").read_text(encoding="utf-8")
    _, m = d.ler(base)
    posicionar(g)
    xml = d.gravar(base, m, g)
    out = ROOT / "templates" / "TitanMatch_starter.drx"
    out.write_text(xml, encoding="utf-8", newline="")
    g2, _ = d.ler(xml)
    ordem, _ = d.ordem_e_posicoes(g2)
    nos = {d._get(n, 1): n for n in g2.nos()}
    print(f"{out.name}: {len(ordem)} nós, {len(d.quadros(xml))} quadros de animação")
    for k in ordem:
        x, y = d.xy(nos[k])
        print(f"   {x:5d},{y:5d}  {(d._get(nos[k], 6) or b'(mixer)').decode()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
