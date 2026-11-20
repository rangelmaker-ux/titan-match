"""Reorganiza os nós dos templates .drx em fileiras de 4 (camada em paralelo na frente).

Uso:  python tools/organizar_arvores.py [templates/*.drx]
Precisa do pacote `zstandard` só se o .drx ainda vier comprimido do Resolve.
O arquivo é regravado com blocos zstd sem compressão (o plugin lê sem bibliotecas).
O original fica em templates/_originais/ (fora do pacote de atualização).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from titan_match import drx_layout  # noqa: E402


def main(argv: list[str]) -> int:
    # A Starter tem layout próprio em duas faixas (tools/criar_starter.py): não reorganizar.
    files = [Path(a) for a in argv] or sorted(p for p in (ROOT / "templates").glob("*.drx")
                                              if p.name != "TitanMatch_starter.drx")
    bak = ROOT / "templates" / "_originais"
    for p in files:
        xml = p.read_text(encoding="utf-8")
        g, _ = drx_layout.ler(xml)
        ordem, pos = drx_layout.ordem_e_posicoes(g)
        bak.mkdir(exist_ok=True)
        if not (bak / p.name).exists():
            shutil.copy2(p, bak / p.name)
        novo = drx_layout.organizar(xml)
        p.write_text(novo, encoding="utf-8", newline="")
        print(f"{p.name}: {len(ordem)} nós, {len(drx_layout.quadros(novo))} quadros de animação")
        nomes = {drx_layout._get(n, 1): (drx_layout._get(n, 6, b"") or b"(mixer)").decode() for n in g.nos()}
        for k in ordem:
            print(f"   {pos[k][0]:5d},{pos[k][1]:5d}  {nomes[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
