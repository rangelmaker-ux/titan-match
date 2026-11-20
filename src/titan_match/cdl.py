"""ASC CDL: modelo, formatação para SetCDL e simulação numpy."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])


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
    """ASC CDL v1.2: (in*slope + offset) com clamp [0,1], ^power, depois saturação (luma Rec.709)."""
    x = rgb * np.asarray(cdl.slope) + np.asarray(cdl.offset)
    x = np.clip(x, 0.0, 1.0) ** np.asarray(cdl.power)
    if cdl.saturation != 1.0:
        luma = np.einsum("...c,c->...", x, REC709_LUMA)[..., None]
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


def fit_cdl(xs: np.ndarray, ys: np.ndarray) -> tuple[CDL, float]:
    """Um CDL (slope/offset/power por canal, sem saturação) que aproxima a curva xs→ys.

    xs, ys: (N, 3), um canal por coluna. Para cada canal: busca em grade do power e, para cada
    power, mínimos quadrados de slope/offset em ys^(1/power) = xs·slope + offset; fica o de menor
    erro no espaço de saída. Devolve o CDL e o erro máximo (0..1).
    """
    xs, ys = np.asarray(xs, np.float64), np.clip(np.asarray(ys, np.float64), 0.0, 1.0)
    slope, offset, power, worst = [], [], [], 0.0
    for c in range(3):
        x, y = xs[:, c], ys[:, c]
        # A reta só vale onde a curva não bateu no limite (o clamp do CDL achata 0 e 1).
        livre = (y > 1e-4) & (y < 1 - 1e-4)
        if livre.sum() < 8:
            livre = np.ones_like(y, bool)
        best = (np.inf, 1.0, 0.0, 1.0)
        for grid in (np.geomspace(0.25, 4.0, 121), None):
            if grid is None:  # refino em volta do melhor
                grid = best[3] * np.geomspace(0.94, 1.06, 41)
            for p in grid:
                a = np.stack([x[livre], np.ones(livre.sum())], axis=1)
                s, o = np.linalg.lstsq(a, y[livre] ** (1.0 / p), rcond=None)[0]
                err = np.abs(np.clip(x * s + o, 0.0, 1.0) ** p - y)
                e = float(np.sqrt(np.mean(err ** 2)))
                if e < best[0]:
                    best = (e, float(s), float(o), float(p))
        _, s, o, p = best
        slope.append(s), offset.append(o), power.append(p)
        worst = max(worst, float(np.max(np.abs(np.clip(x * s + o, 0.0, 1.0) ** p - y))))
    return CDL(tuple(slope), tuple(offset), tuple(power)), worst
