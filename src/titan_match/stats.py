"""Extração de estatísticas de imagem no espaço de trabalho DWG/DI.

Zonas tonais são definidas por posto de luma (percentil) da própria imagem:
sombras = 0–25 %, médios = 25–75 %, altas = 75–100 %. Assim cada zona da
referência é comparada com a zona equivalente do footage, mesmo que a
exposição seja diferente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import colorspaces as cs
from . import profiles as pf

ZONES = {"shadows": (0.0, 0.25), "midtones": (0.25, 0.75), "highlights": (0.75, 1.0)}
PERCENTILES = (1, 10, 25, 50, 75, 90, 99)
HIST_BINS = 64
HUE_BINS = 12


@dataclass
class ZoneStats:
    rgb_mean: np.ndarray  # médias DI por canal
    lab_mean: np.ndarray
    lab_std: np.ndarray
    chroma_mean: float
    luma_mean: float
    pixel_fraction: float


@dataclass
class ImageStats:
    luma_percentiles: dict[int, float]
    zones: dict[str, ZoneStats]
    hist_working: np.ndarray  # (3, HIST_BINS) normalizado, domínio DI
    hist_display: np.ndarray  # (3, HIST_BINS) normalizado, após Output CST
    hue_hist: np.ndarray  # (HUE_BINS,) chroma ponderado, normalizado
    hue_mean_chroma: np.ndarray  # (HUE_BINS,)
    mean_lab: np.ndarray
    mean_chroma: float
    cct_kelvin: float
    tint_duv_proxy: float  # a* médio dos médios (verde<0<magenta)
    contrast_slope: float  # (p90 - p10) da luma DI
    pixel_count: int
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "luma_percentiles": {str(k): round(v, 4) for k, v in self.luma_percentiles.items()},
            "contrast_slope_p90_p10": round(self.contrast_slope, 4),
            "cct_kelvin": round(self.cct_kelvin, 0),
            "tint_a_midtones": round(self.tint_duv_proxy, 3),
            "mean_lab": [round(float(x), 3) for x in self.mean_lab],
            "mean_chroma": round(self.mean_chroma, 3),
            "zones": {
                z: {
                    "rgb_mean_DI": [round(float(x), 4) for x in s.rgb_mean],
                    "lab_mean": [round(float(x), 3) for x in s.lab_mean],
                    "lab_std": [round(float(x), 3) for x in s.lab_std],
                    "chroma_mean": round(s.chroma_mean, 3),
                }
                for z, s in self.zones.items()
            },
        }


def _flatten(img: np.ndarray, max_pixels: int = 60_000) -> np.ndarray:
    px = np.asarray(img, dtype=np.float64).reshape(-1, 3)
    if len(px) > max_pixels:
        step = int(np.ceil(len(px) / max_pixels))
        px = px[::step]
    return px


def zone_masks(luma: np.ndarray) -> dict[str, np.ndarray]:
    order = np.argsort(luma, kind="stable")
    rank = np.empty(len(luma))
    rank[order] = (np.arange(len(luma)) + 0.5) / len(luma)
    return {z: (rank >= lo) & (rank < hi) if hi < 1 else (rank >= lo) for z, (lo, hi) in ZONES.items()}


def _hist(px: np.ndarray) -> np.ndarray:
    h = np.stack([np.histogram(px[:, c], bins=HIST_BINS, range=(0.0, 1.0))[0] for c in range(3)]).astype(float)
    return h / max(h.sum(axis=1, keepdims=True).max(), 1)


def compute_stats(working: np.ndarray, exclude: np.ndarray | None = None) -> ImageStats:
    """Estatísticas de uma imagem JÁ no espaço de trabalho DWG/DI.

    exclude: máscara HxW opcional de pixels a ignorar (ex.: pele, quando a opção
    "separar pele e entorno" está ligada). Se sobrar menos de 5 % da imagem, é ignorada.
    """
    px_all = np.asarray(working, dtype=np.float64).reshape(-1, 3)
    if exclude is not None:
        keep = ~np.asarray(exclude, dtype=bool).reshape(-1)
        if keep.mean() >= 0.05:
            px_all = px_all[keep]
    px = np.clip(_flatten(px_all), 0.0, 1.0)
    luma = pf.working_luma(px)
    lab = pf.working_to_lab(px)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360

    masks = zone_masks(luma)
    zones = {}
    for z, m in masks.items():
        if not m.any():
            m = np.ones_like(m)
        zones[z] = ZoneStats(
            rgb_mean=px[m].mean(axis=0),
            lab_mean=lab[m].mean(axis=0),
            lab_std=lab[m].std(axis=0),
            chroma_mean=float(chroma[m].mean()),
            luma_mean=float(luma[m].mean()),
            pixel_fraction=float(m.mean()),
        )

    bins = (hue / (360 / HUE_BINS)).astype(int) % HUE_BINS
    hue_hist = np.bincount(bins, weights=chroma, minlength=HUE_BINS)
    counts = np.bincount(bins, minlength=HUE_BINS)
    hue_mean_chroma = np.divide(hue_hist, counts, out=np.zeros(HUE_BINS), where=counts > 0)
    hue_hist = hue_hist / max(hue_hist.sum(), 1e-9)

    # Temperatura aparente: cromaticidade média (XYZ) de médios + altas.
    wm = masks["midtones"] | masks["highlights"]
    xyz = cs.lab_to_xyz(lab[wm]).mean(axis=0)
    s = xyz.sum()
    x, y = (xyz[0] / s, xyz[1] / s) if s > 1e-9 else cs.D65
    try:
        cct = cs.xy_to_cct(x, y)
    except ZeroDivisionError:
        cct = float("nan")

    pct = {p: float(np.percentile(luma, p)) for p in PERCENTILES}
    return ImageStats(
        luma_percentiles=pct,
        zones=zones,
        hist_working=_hist(px),
        hist_display=_hist(pf.output_cst(px)),
        hue_hist=hue_hist,
        hue_mean_chroma=hue_mean_chroma,
        mean_lab=lab.mean(axis=0),
        mean_chroma=float(chroma.mean()),
        cct_kelvin=cct,
        tint_duv_proxy=float(zones["midtones"].lab_mean[1]),
        contrast_slope=pct[90] - pct[10],
        pixel_count=len(px),
    )


def histogram_distance(h1: np.ndarray, h2: np.ndarray) -> float:
    """Distância de Wasserstein-1 média por canal entre histogramas (0 = iguais, em unidades de código)."""
    d = 0.0
    for c in range(3):
        a = h1[c] / max(h1[c].sum(), 1e-12)
        b = h2[c] / max(h2[c].sum(), 1e-12)
        d += np.abs(np.cumsum(a) - np.cumsum(b)).sum() / len(a)
    return float(d / 3)
