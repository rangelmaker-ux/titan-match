"""ASC CDL: modelo, formatação para SetCDL e simulação numpy."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])
# Pesos que a Saturation do DaVinci usa (medidos no Resolve 21: L = 0,21 R + 0,70 G + 0,09 B).
SAT_LUMA = np.array([0.21, 0.70, 0.09])


@dataclass
class CDL:
    slope: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    power: tuple[float, float, float] = (1.0, 1.0, 1.0)
    saturation: float = 1.0

    def is_identity(self, tol: float = 1e-6) -> bool:
        return (
            np.allclose(self.slope, 1, atol=tol)
            and np.allclose(self.offset, 0, atol=tol)
            and np.allclose(self.power, 1, atol=tol)
            and abs(self.saturation - 1) < tol
        )

    def to_resolve(self, node_index: int) -> dict:
        """Dicionário no formato de TimelineItem.SetCDL (strings separadas por espaço)."""
        fmt = lambda v: " ".join(f"{x:.6f}" for x in v)  # noqa: E731
        return {
            "NodeIndex": int(node_index),
            "Slope": fmt(self.slope),
            "Offset": fmt(self.offset),
            "Power": fmt(self.power),
            "Saturation": round(float(self.saturation), 6),
        }

    def scaled(self, s: float) -> "CDL":
        """Força do match: interpola entre identidade (s=0) e este CDL (s=1)."""
        s = float(min(max(s, 0.0), 1.0))
        lerp = lambda v, ident: tuple(float(ident + s * (x - ident)) for x in v)  # noqa: E731
        return CDL(lerp(self.slope, 1.0), lerp(self.offset, 0.0), lerp(self.power, 1.0),
                   float(1.0 + s * (self.saturation - 1.0)))

    def as_dict(self) -> dict:
        return {
            "slope": [round(float(x), 6) for x in self.slope],
            "offset": [round(float(x), 6) for x in self.offset],
            "power": [round(float(x), 6) for x in self.power],
            "saturation": round(float(self.saturation), 6),
        }


def apply_cdl(rgb: np.ndarray, cdl: CDL) -> np.ndarray:
    """CDL como o nó do DaVinci aplica (medido no Resolve 21 com ExportLUT).

    (in·slope + offset) sem corte, potência que preserva o sinal (sinal·|x|^power), saturação com os
    pesos do DaVinci (SAT_LUMA). O corte em [0, 1] fica só no fim, para as etapas seguintes.
    """
    x = rgb * np.asarray(cdl.slope) + np.asarray(cdl.offset)
    p = np.asarray(cdl.power)
    if not np.allclose(p, 1.0):
        x = np.sign(x) * np.abs(x) ** p
    if cdl.saturation != 1.0:
        luma = np.einsum("...c,c->...", x, SAT_LUMA)[..., None]
        x = luma + cdl.saturation * (x - luma)
    return np.clip(x, 0.0, 1.0)


def apply_cdl_masked(rgb: np.ndarray, cdl: CDL, mask: np.ndarray | None, soft: float = 2.0) -> np.ndarray:
    """CDL só dentro da máscara (aproxima um nó com chave/qualifier).

    A máscara é suavizada (desfoque gaussiano de `soft` px), como a borda suave de um qualifier,
    para a simulação não mostrar recortes duros.
    """
    if mask is None:
        return apply_cdl(rgb, cdl)
    m = np.asarray(mask, dtype=np.float64)
    if soft > 0 and m.ndim == 2:
        from PIL import Image, ImageFilter

        m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(soft)),
                       dtype=np.float64) / 255.0
    return rgb * (1 - m[..., None]) + apply_cdl(rgb, cdl) * m[..., None]


def apply_chain(rgb: np.ndarray, cdls: list[CDL]) -> np.ndarray:
    for c in cdls:
        rgb = apply_cdl(rgb, c)
    return rgb


def fit_cdl(xs: np.ndarray, ys: np.ndarray, spread: float = 0.15) -> tuple[CDL, float]:
    """Um CDL (slope/offset/power, sem saturação) que aproxima a curva xs→ys, canal a canal.

    xs, ys: (N, 3). Primeiro acha um power comum aos três canais (o tom); depois cada canal pode
    afastar o power até ±`spread` desse valor. Sem esse limite, cada canal cai num power bem
    diferente e o resultado ganha dominante de cor nas sombras/altas. Para cada power, mínimos
    quadrados de slope/offset em ys^(1/power) = xs·slope + offset, só onde a curva não bateu no
    clamp; vence o menor erro RMS no espaço de saída. Devolve o CDL e o erro máximo (0..1).
    """
    xs, ys = np.asarray(xs, np.float64), np.clip(np.asarray(ys, np.float64), 0.0, 1.0)

    def canal(c: int, p: float) -> tuple[float, float, float]:
        x, y = xs[:, c], ys[:, c]
        livre = (y > 1e-4) & (y < 1 - 1e-4)
        if livre.sum() < 8:
            livre = np.ones_like(y, bool)
        a = np.stack([x[livre], np.ones(int(livre.sum()))], axis=1)
        s_, o_ = np.linalg.lstsq(a, y[livre] ** (1.0 / p), rcond=None)[0]
        e = float(np.mean((np.clip(x * s_ + o_, 0.0, 1.0) ** p - y) ** 2))
        return e, float(s_), float(o_)

    comum = (np.inf, 1.0)
    for grid in (np.geomspace(0.4, 2.5, 85), None):
        if grid is None:
            grid = comum[1] * np.geomspace(0.95, 1.05, 31)
        for p in grid:
            e = sum(canal(c, float(p))[0] for c in range(3))
            if e < comum[0]:
                comum = (e, float(p))
    p0 = comum[1]
    slope, offset, power = [], [], []
    for c in range(3):
        best = min(((canal(c, float(p)), float(p)) for p in p0 * np.geomspace(1 - spread, 1 + spread, 41)),
                   key=lambda r: r[0][0])
        (_, s_, o_), p = best
        slope.append(s_), offset.append(o_), power.append(p)
    fit = CDL(tuple(slope), tuple(offset), tuple(power))
    worst = float(np.max(np.abs(apply_cdl(xs, fit) - ys)))
    return fit, worst
