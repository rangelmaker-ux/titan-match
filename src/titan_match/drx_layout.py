"""Layout e animação da árvore de nós dentro do .drx.

O <Body> da versão no .drx é: 1 byte (0x81) + um frame zstd com um protobuf do grafo.
Campos usados (medidos no Resolve 21.1.2):
  grafo (campo 1 do topo):  7 = nó, 8 = ligação, 9 = entrada da fonte, 10 = saída
  nó:       1 = id, 2 = número exibido, 4 = X, 5 = Y, 6 = label
  ligação:  1 = id do nó de origem, 3 = id do nó de destino, 4 = entrada do destino
  saída:    3 -> 4 = id do nó ligado à saída

Os templates que acompanham o plugin são gravados com blocos zstd "raw" (sem compressão),
que qualquer decodificador zstd aceita e que este módulo lê sem biblioteca externa.
`organizar` (rodado pelo tools/organizar_arvores.py) reposiciona os nós em fileiras;
`quadros` gera árvores parciais (1, 2, … nós) para a animação de montagem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
COLS = 4          # nós por fileira na parte em série
DX, DY = 300, 230  # passo entre nós (unidades do editor de nós)
GAP = 150          # folga extra entre a grade em série e a camada em paralelo


# ------------------------------------------------------------------ protobuf mínimo
def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def _enc_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        c = v & 0x7F
        v >>= 7
        if v:
            out.append(c | 0x80)
        else:
            out.append(c)
            return bytes(out)


def parse(b: bytes) -> list[list]:
    """Lista de [campo, tipo, valor]; preserva a ordem para regravar igual."""
    i, out = 0, []
    while i < len(b):
        k, i = _varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 1:
            v, i = b[i:i + 8], i + 8
        elif t == 5:
            v, i = b[i:i + 4], i + 4
        elif t == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"tipo protobuf {t} não suportado")
        out.append([f, t, v])
    if i != len(b):
        raise ValueError("protobuf truncado")
    return out


def dump(fields: list[list]) -> bytes:
    out = bytearray()
    for f, t, v in fields:
        out += _enc_varint((f << 3) | t)
        if t == 0:
            out += _enc_varint(v)
        elif t == 2:
            out += _enc_varint(len(v)) + v
        else:
            out += v
    return bytes(out)


def _get(fields: list[list], f: int, default=None):
    return next((v for ff, _, v in fields if ff == f), default)


def _set(fields: list[list], f: int, value: int) -> None:
    for e in fields:
        if e[0] == f:
            e[2] = value
            return
    fields.append([f, 0, value])


# ------------------------------------------------------------------ zstd
def zstd_raw(data: bytes) -> bytes:
    """Frame zstd válido com blocos sem compressão (Single_Segment, tamanho de 4 bytes)."""
    out = bytearray(ZSTD_MAGIC)
    out.append(0b1010_0000)  # FCS de 4 bytes, single segment, sem checksum
    out += len(data).to_bytes(4, "little")
    pos, step = 0, 128 * 1024 - 1
    while True:
        chunk = data[pos:pos + step]
        pos += len(chunk)
        last = pos >= len(data)
        out += ((len(chunk) << 3) | int(last)).to_bytes(3, "little")  # tipo 0 = raw
        out += chunk
        if last:
            return bytes(out)


def zstd_read(frame: bytes) -> bytes:
    """Lê frames com blocos raw/RLE; frames comprimidos exigem o pacote zstandard."""
    if frame[:4] != ZSTD_MAGIC:
        raise ValueError("não é zstd")
    fhd = frame[4]
    single, dict_flag, fcs_flag = (fhd >> 5) & 1, fhd & 3, fhd >> 6
    i = 5 + (0 if single else 1) + (0, 1, 2, 4)[dict_flag]
    i += (1 if single else 0, 2, 4, 8)[fcs_flag]
    out = bytearray()
    while True:
        h = int.from_bytes(frame[i:i + 3], "little")
        i += 3
        last, btype, size = h & 1, (h >> 1) & 3, h >> 3
        if btype == 0:
            out += frame[i:i + size]
            i += size
        elif btype == 1:
            out += frame[i:i + 1] * size
            i += 1
        else:
            try:
                import zstandard  # só no computador de quem monta os templates
            except ImportError as e:
                raise ValueError("bloco zstd comprimido") from e
            return zstandard.ZstdDecompressor().decompress(frame, max_output_size=64 * 1024 * 1024)
        if last:
            return bytes(out)


# ------------------------------------------------------------------ .drx
_BODY = re.compile(r"(<pClipFullVer>.*?<Body>)([0-9a-fA-F]+)(</Body>)", re.S)


@dataclass
class Grafo:
    top: list[list]      # mensagem de topo do Body
    grafo: list[list]    # campo 1 do topo

    def nos(self) -> list[list[list]]:
        return [parse(v) for f, _, v in self.grafo if f == 7]

    def ligacoes(self) -> list[tuple[int, int, int]]:
        out = []
        for f, _, v in self.grafo:
            if f == 8:
                ln = parse(v)
                out.append((_get(ln, 1), _get(ln, 3), _get(ln, 4, 0)))
        return out

    def entrada(self) -> int | None:
        src = _get(self.grafo, 9)
        sub = _get(parse(src), 3) if src else None
        return _get(parse(sub), 4) if sub else None


def ler(xml: str) -> tuple[Grafo, re.Match]:
    m = _BODY.search(xml)
    if not m:
        raise ValueError("Body da versão não encontrado no .drx")
    raw = bytes.fromhex(m.group(2))
    if raw[:1] != b"\x81":
        raise ValueError("Body com cabeçalho desconhecido")
    top = parse(zstd_read(raw[1:]))
    return Grafo(top, parse(_get(top, 1))), m


def gravar(xml: str, m: re.Match, g: Grafo) -> str:
    top = [[f, t, dump(g.grafo) if f == 1 else v] for f, t, v in g.top]
    body = (b"\x81" + zstd_raw(dump(top))).hex()
    return xml[:m.start(2)] + body + xml[m.end(2):]


# ------------------------------------------------------------------ layout
def ordem_e_posicoes(g: Grafo) -> tuple[list[int], dict[int, tuple[int, int]]]:
    """Ordem de montagem dos nós e a posição de cada um.

    Série em fileiras de COLS nós (esquerda→direita, de cima para baixo); a camada em
    paralelo fica na frente da grade, empilhada e centrada; mixer e o resto seguem
    na linha do centro.
    """
    nos = {_get(n, 1): n for n in g.nos()}
    saidas: dict[int, list[tuple[int, int]]] = {k: [] for k in nos}
    entradas: dict[int, list[int]] = {k: [] for k in nos}
    for a, b, porta in g.ligacoes():
        if a in nos and b in nos:
            saidas[a].append((porta, b))
            entradas[b].append(a)
    x0 = min(_get(n, 4, 0) for n in nos.values())
    y0 = min(_get(n, 5, 0) for n in nos.values())

    comeco = g.entrada()
    if comeco not in nos:
        comeco = next((k for k in nos if not entradas[k]), next(iter(nos)))
    serie, atual, vistos = [], comeco, set()
    while atual is not None and atual not in vistos:
        vistos.add(atual)
        serie.append(atual)
        prox = [b for _, b in saidas[atual]]
        atual = prox[0] if len(prox) == 1 and len(entradas[prox[0]]) == 1 else None

    pos: dict[int, tuple[int, int]] = {}
    for i, k in enumerate(serie):
        pos[k] = (x0 + (i % COLS) * DX, y0 + (i // COLS) * DY)
    linhas = (len(serie) + COLS - 1) // COLS
    centro = y0 + (linhas - 1) * DY // 2
    x = x0 + min(len(serie), COLS) * DX + GAP
    ordem = list(serie)

    ultimo = serie[-1]
    while True:
        ramos = sorted(saidas[ultimo])
        if not ramos:
            break
        ramos_ids = [b for _, b in ramos if b not in pos]
        if not ramos_ids:
            break
        if len(ramos_ids) == 1:  # continua em linha, no centro
            k = ramos_ids[0]
            pos[k], ordem, x, ultimo = (x, centro), ordem + [k], x + DX, k
            continue
        topo = centro - (len(ramos_ids) - 1) * DY // 2
        for j, k in enumerate(ramos_ids):
            pos[k] = (x, topo + j * DY)
            ordem.append(k)
        x += DX
        juncao = {b for k in ramos_ids for _, b in saidas[k]}
        if len(juncao) != 1:
            break
        k = juncao.pop()
        if k in pos:
            break
        pos[k], ordem, x, ultimo = (x, centro), ordem + [k], x + DX, k

    resto = [k for k in nos if k not in pos]  # algo fora do padrão: fileira de baixo
    for j, k in enumerate(resto):
        pos[k] = (x0 + j * DX, y0 + (linhas + 1) * DY)
        ordem.append(k)
    return ordem, pos


def organizar(xml: str) -> str:
    g, m = ler(xml)
    _, pos = ordem_e_posicoes(g)
    novo = []
    for f, t, v in g.grafo:
        if f == 7:
            n = parse(v)
            px, py = pos[_get(n, 1)]
            _set(n, 4, px)
            _set(n, 5, py)
            v = dump(n)
        novo.append([f, t, v])
    g.grafo = novo
    return gravar(xml, m, g)


def quadros(xml: str) -> list[str]:
    """Árvores parciais (1..N-1 nós, na ordem de montagem) para a animação.

    Cada quadro só tem as ligações entre nós presentes; a saída vai para o último nó em
    série já montado. O quadro final é o próprio template, aplicado por quem chama.
    """
    g, m = ler(xml)
    ordem, _ = ordem_e_posicoes(g)
    saida_id = None
    out_msg = _get(g.grafo, 10)
    if out_msg:
        sub = _get(parse(out_msg), 3)
        saida_id = _get(parse(sub), 4) if sub else None
    entrada = g.entrada()
    nos = {_get(n, 1): n for n in g.nos()}
    numeros = {k: _get(n, 2, 0) for k, n in nos.items()}
    ligs = g.ligacoes()
    # nós que levam a imagem até a saída: o último presente deles recebe a saída
    caminho = [k for k in ordem if k == saida_id or k in _caminho_principal(g, entrada)]
    frames = []
    for n in range(1, len(ordem)):
        presentes = set(ordem[:n])
        if entrada not in presentes:
            continue
        alvo = saida_id if saida_id in presentes else next(
            (k for k in reversed(ordem[:n]) if k in caminho), ordem[0])
        renum = {k: i + 1 for i, k in enumerate(sorted(presentes, key=lambda k: numeros[k]))}
        grafo = []
        for f, t, v in g.grafo:
            if f == 7:
                no = parse(v)
                k = _get(no, 1)
                if k not in presentes:
                    continue
                _set(no, 2, renum[k])
                v = dump(no)
            elif f == 8:
                ln = parse(v)
                if _get(ln, 1) not in presentes or _get(ln, 3) not in presentes:
                    continue
            elif f == 10:
                saida = parse(v)
                sub = parse(_get(saida, 3))
                _set(sub, 4, alvo)
                saida = [[ff, tt, dump(sub) if ff == 3 else vv] for ff, tt, vv in saida]
                v = dump(saida)
            grafo.append([f, t, v])
        frames.append(gravar(xml, m, Grafo(g.top, grafo)))
    return frames


def _caminho_principal(g: Grafo, comeco: int | None) -> set[int]:
    """Nós alcançáveis pela primeira saída de cada nó (a linha que segue até a saída)."""
    prox: dict[int, list[tuple[int, int]]] = {}
    for a, b, porta in g.ligacoes():
        prox.setdefault(a, []).append((porta, b))
    out, atual = set(), comeco
    while atual is not None and atual not in out:
        out.add(atual)
        seg = sorted(prox.get(atual, []))
        atual = seg[0][1] if seg else None
    return out
