"""Color transfer estatístico clássico, por zona tonal em Lab / DI.

Os nós ficam em série, então cada correção é calculada sobre o footage
já processado pelos nós anteriores (simulação CDL em numpy). Isso evita
que, por exemplo, o Gain desfaça o que o Lift corrigiu.

Com options.source_exclude (máscara de pele), as estatísticas do footage
ignoram a pele ("separar pele e entorno"); a referência é tratada igual
pelo engine.
"""
from __future__ import annotations

import numpy as np

from .. import mapping
from ..cdl import apply_cdl
from ..stats import ImageStats, compute_stats
from .base import Matcher, MatchOptions, MatchResult, register


@register
class StatisticalZoneLabMatcher(Matcher):
    name = "statistical_zone_lab"

    def match(self, source_working: np.ndarray, reference: ImageStats, options: MatchOptions) -> MatchResult:
        img = np.clip(np.asarray(source_working, dtype=np.float64), 0.0, 1.0)
        ex = options.source_exclude
        stats = lambda im: compute_stats(im, exclude=ex)  # noqa: E731
        corrections = {}
        trace = []

        steps = [
            ("white_balance", mapping.map_white_balance),
            ("exposure_contrast", mapping.map_exposure_contrast),
            ("shadows", mapping.map_lift),
            ("midtones", mapping.map_gamma),
            ("highlights", mapping.map_gain),
        ]
        cur = stats(img)
        for i, (role, fn) in enumerate(steps):
            options.report(20 + i * 8, f"Calculando {role}…")
            corr = fn(cur, reference)
            corrections[role] = corr
            img = apply_cdl(img, corr.cdl)
            cur = stats(img)
            trace.append({"after": role, "luma_p50": round(cur.luma_percentiles[50], 4), "chroma": round(cur.mean_chroma, 3)})

        # 07 e 08 se acoplam (saturação escala a*/b*): ponto fixo em 3 passadas.
        options.report(62, "Calculando color balance e saturação…")
        pre_balance, pre_stats = img, cur
        sat_hint = 1.0
        for _ in range(3):
            bal = mapping.map_color_balance(pre_stats, reference, sat_hint=sat_hint)
            img = apply_cdl(pre_balance, bal.cdl)
            cur = stats(img)
            sat = mapping.map_saturation(cur, reference, cur_image=img, exclude=ex)
            sat_hint = sat.cdl.saturation
        corrections["color_balance"] = bal
        trace.append({"after": "color_balance", "chroma": round(cur.mean_chroma, 3)})
        corrections["saturation"] = sat
        img = apply_cdl(img, sat.cdl)
        trace.append({"after": "saturation", "chroma": round(stats(img).mean_chroma, 3)})

        corrections["look"] = mapping.map_look(options.film_emulation)
        result = MatchResult(corrections, self.name, {"trace": trace})
        result.validate()
        return result
