"""Curvas de transferência, gamuts e conversões de cor (numpy puro).

Todas as constantes vêm dos white papers dos fabricantes; os testes as
conferem contra a biblioteca colour-science quando ela está instalada.
"""
from __future__ import annotations

import numpy as np

D65 = (0.3127, 0.3290)

# Primárias CIE xy (R, G, B) de cada gamut.
GAMUTS: dict[str, tuple[tuple[float, float], ...]] = {
    "Rec.709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "DaVinci Wide Gamut": ((0.8000, 0.3130), (0.1682, 0.9877), (0.0790, -0.1155)),
    "S-Gamut3.Cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "V-Gamut": ((0.730, 0.280), (0.165, 0.840), (0.100, -0.030)),
    "Cinema Gamut": ((0.740, 0.270), (0.170, 1.140), (0.080, -0.100)),
    "ARRI Wide Gamut 3": ((0.6840, 0.3130), (0.2210, 0.8480), (0.0861, -0.1020)),
    "REDWideGamutRGB": ((0.780308, 0.304253), (0.121595, 1.493994), (0.095612, -0.084589)),
    "Blackmagic Wide Gamut": ((0.7177215, 0.3171181), (0.2280410, 0.8615690), (0.1005841, -0.0820452)),
    "D-Gamut": ((0.71, 0.31), (0.21, 0.88), (0.09, -0.08)),
    "S-Gamut3": ((0.730, 0.280), (0.140, 0.855), (0.100, -0.050)),  # = S-Gamut
    "Venice S-Gamut3.Cine": ((0.775902, 0.274502), (0.188683, 0.828685), (0.101337, -0.089188)),
    "Rec.2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),  # = F-Gamut = N-Gamut
    "F-Gamut C": ((0.7347, 0.2653), (0.0263, 0.9737), (0.1173, -0.0224)),
    "ARRI Wide Gamut 4": ((0.7347, 0.2653), (0.1424, 0.8576), (0.0991, -0.0308)),
    "Protune Native": ((0.69848, 0.193026), (0.329555, 1.024597), (0.108443, -0.034679)),
}


def rgb_to_xyz_matrix(gamut: str, white=D65) -> np.ndarray:
    prim = np.array(GAMUTS[gamut], dtype=np.float64)
    xyz = np.stack([prim[:, 0] / prim[:, 1], np.ones(3), (1 - prim[:, 0] - prim[:, 1]) / prim[:, 1]])
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    s = np.linalg.solve(xyz, w)
    return xyz * s


def gamut_matrix(src: str, dst: str) -> np.ndarray:
    """Matriz linear src->dst (todos os gamuts usados têm branco D65; sem CAT)."""
    return np.linalg.inv(rgb_to_xyz_matrix(dst)) @ rgb_to_xyz_matrix(src)


def apply_matrix(m: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    return np.einsum("ij,...j->...i", m, rgb)


# --------------------------------------------------------------- curvas (log -> linear cena)

def slog3_decode(y):
    y = np.asarray(y, dtype=np.float64)
    cv = y * 1023.0
    return np.where(
        y >= 171.2102946929 / 1023.0,
        10.0 ** ((cv - 420.0) / 261.5) * (0.18 + 0.01) - 0.01,
        (cv - 95.0) * 0.01125000 / (171.2102946929 - 95.0),
    )


def vlog_decode(y):
    y = np.asarray(y, dtype=np.float64)
    b, c, d = 0.00873, 0.241514, 0.598206
    return np.where(y < 0.181, (y - 0.125) / 5.6, 10.0 ** ((y - d) / c) - b)


def clog3_decode(y):
    """Canon Log 3 v1.2 (código normalizado; as constantes já estão em faixa legal), como o CST do DaVinci."""
    t = np.asarray(y, dtype=np.float64)
    x = np.where(
        t < 0.097465473,
        -(10.0 ** ((0.12783901 - t) / 0.36726845) - 1.0) / 14.98325,
        np.where(
            t <= 0.15277891,
            (t - 0.12512219) / 1.9754798,
            (10.0 ** ((t - 0.12240537) / 0.36726845) - 1.0) / 14.98325,
        ),
    )
    return x  # sem o fator 0,9: o CST do DaVinci 21 não aplica (medido: razão 1/0,9)


def logc3_decode(t):
    """ARRI LogC3, EI 800."""
    t = np.asarray(t, dtype=np.float64)
    cut, a, b, c, d, e, f = 0.010591, 5.555556, 0.052272, 0.247190, 0.385537, 5.367655, 0.092809
    return np.where(t > e * cut + f, (10.0 ** ((t - d) / c) - b) / a, (t - f) / e)


def log3g10_decode(y):
    y = np.asarray(y, dtype=np.float64)
    a, b, c, g = 0.224282, 155.975327, 0.01, 15.1927
    return np.where(y < 0.0, y / g, (10.0 ** (y / a) - 1.0) / b) - c


def bmdfilm_gen5_decode(y):
    y = np.asarray(y, dtype=np.float64)
    A, B, C, D, E = 0.08692876065491224, 0.005494072432257808, 0.5300133392291939, 8.283605932402494, 0.09246575342465753
    log_cut = D * 0.005 + E
    return np.where(y < log_cut, (y - E) / D, np.exp((y - C) / A) - B)


def dlog_decode(y):
    y = np.asarray(y, dtype=np.float64)
    return np.where(y <= 0.14, (y - 0.0929) / 6.025, (10.0 ** (3.89616 * y - 2.27752) - 0.0108) / 0.9892)


def _legal_to_full(y):
    return (np.asarray(y, dtype=np.float64) * 1023.0 - 64.0) / 876.0


def slog2_decode(y):
    """Sony S-Log2 (S-Log com escala 219/155), saída em reflectância."""
    y = np.asarray(y, dtype=np.float64)
    x = _legal_to_full(y)
    lin = np.where(y >= 0.0882512915134, 10.0 ** ((x - 0.616596 - 0.03) / 0.432699) - 0.037584,
                   (x - 0.030001222851889303) / 5.0)
    return 219.0 * lin * 0.9 / 155.0


def clog_decode(y):
    """Canon Log v1.2 (constantes em faixa legal), como o CST do DaVinci."""
    t = np.asarray(y, dtype=np.float64)
    k = 0.12512248
    x = np.where(t < k, -(10.0 ** ((k - t) / 0.45310179) - 1) / 10.1596, (10.0 ** ((t - k) / 0.45310179) - 1) / 10.1596)
    return x  # sem o fator 0,9: o CST do DaVinci 21 não aplica (medido: razão 1/0,9)


def clog2_decode(y):
    """Canon Log 2 v1.2."""
    t = np.asarray(y, dtype=np.float64)
    k = 0.092864125
    x = np.where(t < k, -(10.0 ** ((k - t) / 0.24136077) - 1) / 87.09937546,
                 (10.0 ** ((t - k) / 0.24136077) - 1) / 87.09937546)
    return x  # sem o fator 0,9: o CST do DaVinci 21 não aplica (medido: razão 1/0,9)


def _flog(y, cut2, a, b, c, d, e, f):
    y = np.asarray(y, dtype=np.float64)
    return np.where(y < cut2, (y - f) / e, (10.0 ** ((y - d) / c)) / a - b / a)


def flog_decode(y):
    """Fujifilm F-Log."""
    return _flog(y, 0.100537775223865, 0.555556, 0.009468, 0.344676, 0.790453, 8.735631, 0.092864)


def flog2_decode(y):
    """Fujifilm F-Log2 (também usado em F-Log2 C)."""
    return _flog(y, 0.100686685370811, 5.555556, 0.064829, 0.245281, 0.384316, 8.799461, 0.092864)


def nlog_decode(y):
    """Nikon N-Log."""
    y = np.asarray(y, dtype=np.float64)
    a, b, c, d = 0.635386119257087, 0.0075, 0.1466275659824047, 0.6050830889540567
    return np.where(y < 0.4418377321603128, np.sign(y / a) * np.abs(y / a) ** 3 - b, np.exp((y - d) / c))


def logc4_decode(y):
    """ARRI LogC4."""
    y = np.asarray(y, dtype=np.float64)
    a, b, c, s, t = 2231.8263090676883, 0.9071358748778103, 0.09286412512218964, 0.1135972086105891, -0.01805699611991131
    return np.where(y >= 0, (2.0 ** (14 * ((y - c) / b) + 6) - 64) / a, y * s + t)


def apple_log_decode(y):
    """Apple Log (iPhone 15 Pro+)."""
    P = np.asarray(y, dtype=np.float64)
    R0, Rt, sigma, beta, gamma, delta = -0.05641088, 0.01, 47.28711236, 0.00964052, 0.08550479, 0.69336945
    Pt = sigma * (Rt - R0) ** 2
    return np.where(P >= Pt, 2.0 ** ((P - delta) / gamma) - beta,
                    np.where(P >= 0, np.sqrt(np.maximum(P, 0) / sigma) + R0, R0))


def llog_decode(y):
    """Leica L-Log."""
    y = np.asarray(y, dtype=np.float64)
    a, b, c, d, e, f = 8.0, 0.09, 0.27, 1.3, 0.0115, 0.6
    return np.where(y <= 0.138, (y - b) / a, (10.0 ** ((y - f) / c) - e) / d)


def protune_decode(y):
    """GoPro Protune Flat."""
    y = np.asarray(y, dtype=np.float64)
    return (113.0 ** y - 1) / 112.0


def gamma24_decode(y):
    return np.power(np.clip(np.asarray(y, dtype=np.float64), 0.0, None), 2.4)


def gamma24_encode(x):
    return np.power(np.clip(np.asarray(x, dtype=np.float64), 0.0, None), 1.0 / 2.4)


# --------------------------------------------------------------- DaVinci Intermediate

DI_A, DI_B, DI_C, DI_M = 0.0075, 7.0, 0.07329248, 10.44426855
DI_LIN_CUT, DI_LOG_CUT = 0.00262409, 0.02740668


def di_encode(x):
    x = np.asarray(x, dtype=np.float64)
    return np.where(x <= DI_LIN_CUT, x * DI_M, (np.log2(np.maximum(x, DI_LIN_CUT) + DI_A) + DI_B) * DI_C)


def di_decode(y):
    y = np.asarray(y, dtype=np.float64)
    return np.where(y <= DI_LOG_CUT, y / DI_M, 2.0 ** (y / DI_C - DI_B) - DI_A)


# --------------------------------------------------------------- Lab

def xyz_to_lab(xyz: np.ndarray, white=D65) -> np.ndarray:
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    r = np.asarray(xyz, dtype=np.float64) / w
    eps, k = 216 / 24389, 24389 / 27
    f = np.where(r > eps, np.cbrt(np.maximum(r, 0)), (k * r + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_to_xyz(lab: np.ndarray, white=D65) -> np.ndarray:
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    eps, k = 216 / 24389, 24389 / 27
    f = np.stack([fx, fy, fz], axis=-1)
    r = np.where(f ** 3 > eps, f ** 3, (116 * f - 16) / k)
    return r * w


def xy_to_cct(x: float, y: float) -> float:
    """McCamy (1992). Válido aprox. 2000–12500 K."""
    n = (x - 0.3320) / (0.1858 - y)
    return float(449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33)
