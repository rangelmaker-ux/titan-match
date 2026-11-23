"""Controles nativos das Primárias do DaVinci (Offset, Gain, Gamma, Saturation) gravados no .drx.

Em vez de `SetCDL` (que aparece no nó como "Primary Balance", com Temp/Contrast/rodas zerados),
o plugin grava os valores direto nos controles que o colorista usa, para ele ajustar a partir dali.

Tudo medido no DaVinci Resolve 21.1 (nó com um controle por vez -> TimelineItem.ExportLUT):
  * ordem dentro do nó: Gain, depois Offset, depois Gamma, depois Saturation:
    (x·gain + offset)^(1/(1+gamma)), que é exatamente o ASC CDL (slope, offset, power).
  * Com Lum Mix 100 (padrão) os controles mestres (Y) agem só na luminância e as rodas R/G/B
    preservam a luminância de cada pixel (matriz). Com Lum Mix 0 os mestres não fazem nada e as
    rodas R/G/B viram ganho e potência puros por canal: é assim que o plugin grava (igual ao CDL).
  * Offset: soma OFFSET_K × valor gravado (o campo mostra 25 + 25 × valor gravado).
  * Gamma da roda gravado g: potência 1/(1+g) (o campo mostra g/4).
  * Saturation: L + s·(x − L), com L = 0,21 R + 0,70 G + 0,09 B (campo mostra 50 × s).
Os números de cada parâmetro foram lidos de um .drx exportado depois de preencher os campos à mão.
"""
from __future__ import annotations

import struct

import numpy as np

from . import drx_layout as d
from .cdl import CDL

TIPO_PRIMARIAS = 1

GAIN_RGB = (0x600001D, 0x600001E, 0x600001F)
GAIN_Y = 0x6000020
GAMMA_RGB = (0x6000022, 0x6000023, 0x6000024)
GAMMA_Y = 0x6000025
LIFT_RGB = (0x6000018, 0x6000019, 0x600001A)
LIFT_Y = 0x600001B
OFFSET_RGB = (0x600007D, 0x600007E, 0x600007F)
SAT = 0x6000005
HUE = 0x6000004
CONTRAST = 0x860000C1
PIVOT = 0x860000C0
TEMP = 0x86000115
TINT = 0x86000116
COLOR_BOOST = 0x86000112
SHADOWS = 0x86000111
HIGHLIGHTS = 0x86000110
MID_DETAIL = 0x86000113
LUM_MIX = 0x8600000B

# Paleta Blur (mesmo bloco das Primárias; abas Blur/Sharpen/Mist usam os mesmos campos):
BLUR_RADIUS = (0x86000052, 0x86000053, 0x86000054)   # gravado (r − 0,5)·2; < 0,5 nitidiza, > 0,5 desfoca
BLUR_HV = (0x86000056, 0x86000057, 0x86000058)       # gravado (v − 0,5)·2
BLUR_SCALING = (0x8600005B, 0x8600005C, 0x8600005D)  # direto
SHARP_LEVEL = (0x86000060, 0x86000061, 0x86000062)   # gravado ÷ 100
SHARP_CORING = (0x86000065, 0x86000066, 0x86000067)  # gravado ÷ 100
MIST_MIX = (0x8600006A, 0x8600006B, 0x8600006C)      # gravado ÷ 100 (padrão 100)

OFFSET_K = 0.18326                         # Offset gravado 1.0 soma 0,18326
REC709 = np.array([0.2126, 0.7152, 0.0722])  # média que o DaVinci tira dos deltas das rodas


def from_cdl(cdl: CDL) -> dict[int, float]:
    """Parâmetros das Primárias que reproduzem o CDL exatamente (Lum Mix 0, rodas R/G/B)."""
    out: dict[int, float] = {LUM_MIX: 0.0}
    for pid, sc in zip(GAIN_RGB, cdl.slope):
        if abs(sc - 1) > 1e-7:
            out[pid] = float(sc)
    for pid, o in zip(OFFSET_RGB, cdl.offset):
        if abs(o) > 1e-7:
            out[pid] = float(o) / OFFSET_K
    for pid, pw in zip(GAMMA_RGB, cdl.power):
        if abs(pw - 1) > 1e-7:
            out[pid] = 1.0 / float(pw) - 1.0
    if abs(cdl.saturation - 1) > 1e-7:
        out[SAT] = float(cdl.saturation)
    return out


def to_cdl(params: dict[int, float]) -> CDL:
    """CDL equivalente aos parâmetros gravados com Lum Mix 0 (para a simulação)."""
    slope = tuple(params.get(pid, 1.0) for pid in GAIN_RGB)
    offset = tuple(params.get(pid, 0.0) * OFFSET_K for pid in OFFSET_RGB)
    power = tuple(1.0 / (1.0 + params.get(pid, 0.0)) for pid in GAMMA_RGB)
    return CDL(slope, offset, power, params.get(SAT, 1.0))


def nitidez(radius: float, mix: float | None = None) -> dict[int, float]:
    """Paleta Blur: radius como no painel (0,5 = neutro); mix em 0..100 (Mist)."""
    out = {pid: (float(radius) - 0.5) * 2.0 for pid in BLUR_RADIUS}
    if mix is not None:
        out.update({pid: float(mix) / 100.0 for pid in MIST_MIX})
    return out


def legivel(params: dict[int, float]) -> dict[str, object]:
    """Como os valores aparecem no painel Primaries do DaVinci (rodas: R, G, B)."""
    out: dict[str, object] = {}
    if any(p in params for p in GAIN_RGB):
        out["Gain"] = [round(params.get(p, 1.0), 3) for p in GAIN_RGB]
    if any(p in params for p in OFFSET_RGB):
        out["Offset"] = [round(25 + 25 * params.get(p, 0.0), 2) for p in OFFSET_RGB]
    if any(p in params for p in GAMMA_RGB):
        out["Gamma"] = [round(params.get(p, 0.0) / 4, 3) for p in GAMMA_RGB]
    if SAT in params:
        out["Sat"] = round(50 * params[SAT], 2)
    if BLUR_RADIUS[0] in params:
        out["Blur Radius"] = round(0.5 + params[BLUR_RADIUS[0]] / 2, 3)
    if MIST_MIX[0] in params:
        out["Mist Mix"] = round(100 * params[MIST_MIX[0]], 1)
    return out


def _bloco(params: dict[int, float]) -> list:
    ps = [[3, 2, d.dump([[1, 0, pid], [2, 2, d.dump([[1, 5, struct.pack("<f", float(v))]])]])]
          for pid, v in sorted(params.items())]
    corpo = d.dump([[2, 2, d.dump([[1, 0, 1]] + ps)]])
    return [1, 2, d.dump([[1, 0, TIPO_PRIMARIAS], [3, 0, 1], [6, 2, corpo]])]


def campo_correcao(atual: bytes, params: dict[int, float]) -> bytes:
    """Campo 9 do nó com o bloco das Primárias trocado pelos `params` (o resto do nó fica igual)."""
    resto = [it for it in d.parse(atual or b"")
             if not (it[0] == 1 and d._get(d.parse(it[2]), 1) == TIPO_PRIMARIAS)]
    return d.dump(([_bloco(params)] if params else []) + resto)


def ler(atual: bytes) -> dict[int, float]:
    """Parâmetros das Primárias gravados num nó (vazio se não houver)."""
    out: dict[int, float] = {}
    for f, _, v in d.parse(atual or b""):
        if f != 1:
            continue
        blk = d.parse(v)
        if d._get(blk, 1) != TIPO_PRIMARIAS:
            continue
        for ff, _, pv in d.parse(d._get(d.parse(d._get(blk, 6)), 2)):
            if ff == 3:
                pm = d.parse(pv)
                val = d.parse(d._get(pm, 2))
                if val and val[0][1] == 5:
                    out[d._get(pm, 1)] = struct.unpack("<f", val[0][2])[0]
    return out


def aplicar_no_drx(xml: str, por_rotulo: dict[str, dict[int, float]]) -> str:
    """Grava as Primárias nos nós do .drx (achados pelo rótulo)."""
    alvo = {k.casefold(): v for k, v in por_rotulo.items()}
    g, m = d.ler(xml)
    novo = []
    for f, t, v in g.grafo:
        if f == 7:
            n = d.parse(v)
            lab = (d._get(n, 6) or b"").decode("utf-8", "replace").casefold()
            if lab in alvo:
                for item in n:
                    if item[0] == 9:
                        item[2] = campo_correcao(item[2], alvo[lab])
                v = d.dump(n)
        novo.append([f, t, v])
    g.grafo = novo
    return d.gravar(xml, m, g)
