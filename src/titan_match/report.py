"""Relatório do dry-run (texto para aprovação e JSON para registro)."""
from __future__ import annotations

import json
from pathlib import Path

from .nodes import GradePlan


def format_dry_run(plan: GradePlan) -> str:
    lines = [
        "TITAN MATCH — DRY-RUN (nada foi escrito no Resolve)",
        f"Profile: {plan.profile_key}  |  Matcher: {plan.matcher}  |  Força: {round(plan.strength * 100)} %",
        f"Árvore: {plan.template_title or plan.template_key}  ({plan.template_reason})",
        f"Nós ligados: {sum(n.enabled for n in plan.nodes)} de {len(plan.nodes)}",
        "",
    ]
    for n in plan.nodes:
        state = "" if n.enabled else "  [DESABILITADO]"
        lines.append(f"[{n.label}]{state}")
        if n.lut_path:
            lines.append(f"    LUT: {n.lut_path}")
        if n.cdl is not None:
            d = n.cdl.as_dict()
            lines.append(f"    Slope  {d['slope']}")
            lines.append(f"    Offset {d['offset']}")
            lines.append(f"    Power  {d['power']}")
            lines.append(f"    Sat    {d['saturation']}")
        for p in n.provenance:
            lines.append(f"    · {p.param}: {p.formula}")
            lines.append(f"      medido: {json.dumps(p.measured, ensure_ascii=False)}")
            if p.note:
                lines.append(f"      {p.note}")
        for note in n.notes:
            lines.append(f"    ! {note}")
        lines.append("")
    v = plan.verification
    if v:
        lines.append("CONFERÊNCIA (simulada):")
        lines.append(f"    distância de histograma vs referência: antes {v['hist_dist_display_antes']} -> "
                     f"depois {v['hist_dist_display_depois']}  ({'melhorou' if v['melhorou'] else 'NÃO melhorou'})")
        lines.append(f"    ΔLab médios: antes {v['delta_lab_medios_antes']} -> depois {v['delta_lab_medios_depois']}")
    for w in plan.warnings:
        lines.append(f"AVISO: {w}")
    return "\n".join(lines)


def save_plan_json(plan: GradePlan, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
