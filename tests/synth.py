"""Gerador de imagens sintéticas para os testes (sem Resolve, sem arquivos)."""
from __future__ import annotations

import numpy as np

from titan_match import colorspaces as cs
from titan_match import profiles as pf
from titan_match.cdl import CDL, apply_chain


def linear_scene(h: int = 96, w: int = 128, seed: int = 0) -> np.ndarray:
    """Cena linear DWG: rampa de cinza + manchas coloridas + ruído leve."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    ramp = 0.005 * (2.0 ** (x / (w - 1) * 9.0))  # ~0.005 .. 2.56 (9 stops)
    img = np.repeat(ramp[..., None], 3, axis=-1)
    patches = [
        ((0.0, 0.35), (0.60, 0.30, 0.20)),  # pele
        ((0.35, 0.55), (0.10, 0.25, 0.08)),  # folhagem
        ((0.55, 0.75), (0.08, 0.12, 0.35)),  # céu
    ]
    for (a, b), col in patches:
        m = (y >= a * h) & (y < b * h) & (x % 32 < 20)
        tone = (0.4 + 1.2 * x / (w - 1))[m][:, None]
        img[m] = np.asarray(col) * tone
    img *= 1 + 0.02 * rng.standard_normal(img.shape)
    return np.clip(img, 1e-5, None)


def encode_with_profile(lin_dwg: np.ndarray, profile_key: str) -> np.ndarray:
    """Inverte numericamente a curva do profile (decodes são monótonas)."""
    prof = pf.get_profile(profile_key)
    cam_lin = cs.apply_matrix(cs.gamut_matrix(pf.WORKING_GAMUT, prof.gamut), lin_dwg)
    codes = np.linspace(0.0, 1.0, 200001)
    lin = prof.decode(codes)
    return np.interp(cam_lin, lin, codes)


def known_look() -> list[CDL]:
    """Look conhecido aplicado no domínio DI para criar a referência."""
    return [
        CDL(offset=(0.02, 0.0, -0.025)),  # mais quente
        CDL(slope=(1.25,) * 3, offset=(-0.08,) * 3),  # mais contraste
        CDL(saturation=1.3),
    ]


def make_pair(profile_key: str = "sony_slog3", seed: int = 0, look: list[CDL] | None = None):
    lin = linear_scene(seed=seed)
    footage_log = encode_with_profile(lin, profile_key)
    working = cs.di_encode(lin)
    look = known_look() if look is None else look
    reference = pf.output_cst(apply_chain(np.clip(working, 0, 1), look))
    return footage_log, reference
