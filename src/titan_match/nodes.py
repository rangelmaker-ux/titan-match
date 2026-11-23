"""Definição da árvore de nós Titan Match e do plano de grade (dry-run)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cdl import CDL


def _legivel(p):
    if not p:
        return None
    from .primarias import legivel

    return legivel(p)

# Ordem fixa e não negociável: um nó por responsabilidade.
NODE_ROLES: list[tuple[str, str, str]] = [
    # (role, label, cor do nó no Resolve)
    ("input_cst", "01 - Input CST", "Teal"),
    ("white_balance", "02 - White Balance", "Yellow"),
    ("exposure_contrast", "03 - Exposure & Contraste", "Orange"),
    ("shadows", "04 - Shadows (Lift)", "Navy"),
    ("midtones", "05 - Midtones (Gamma)", "Blue"),
    ("highlights", "06 - Highlights (Gain)", "Apricot"),
    ("color_balance", "07 - Color Balance", "Purple"),
    ("saturation", "08 - Saturacao", "Pink"),
    ("look", "09 - Look / Film Emulation", "Brown"),
    ("output_cst", "10 - Output CST", "Teal"),
]
ROLES = [r for r, _, _ in NODE_ROLES]
LABELS = {r: l for r, l, _ in NODE_ROLES}
COLORS = {r: c for r, _, c in NODE_ROLES}
CORRECTION_ROLES = ROLES[1:9]


@dataclass
class Provenance:
    """De onde veio um parâmetro: fórmula + estatísticas medidas."""

    param: str
    formula: str
    measured: dict[str, Any]
    note: str = ""

    def as_dict(self) -> dict:
        d = {"param": self.param, "formula": self.formula, "measured": self.measured}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class NodeCorrection:
    role: str
    cdl: CDL = field(default_factory=CDL)
    provenance: list[Provenance] = field(default_factory=list)
    enabled: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class NodeSpec:
    index_in_block: int  # 1..10
    role: str
    label: str
    color: str
    cdl: CDL | None = None  # None para nós de CST (só LUT)
    lut_path: str | None = None
    enabled: bool = True
    # CST nativo do DaVinci (ResolveFX Color Space Transform) no lugar do LUT; lut_path fica como reserva
    # para quando a árvore já está no clipe sem o CST.
    native_cst: str | None = None
    # Controles das Primárias do DaVinci (id do parâmetro -> valor gravado) que reproduzem o `cdl`;
    # gravados direto no .drx quando a árvore é aplicada numa versão nova (ver primarias.py).
    primarias: dict[int, float] | None = None
    provenance: list[Provenance] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "block_index": self.index_in_block,
            "role": self.role,
            "label": self.label,
            "color": self.color,
            "enabled": self.enabled,
            "cdl": self.cdl.as_dict() if self.cdl else None,
            "lut": self.lut_path,
            "cst": self.native_cst,
            "primarias": _legivel(self.primarias),
            "provenance": [p.as_dict() for p in self.provenance],
            "notes": self.notes,
        }


@dataclass
class GradePlan:
    profile_key: str
    matcher: str
    nodes: list[NodeSpec]
    verification: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    template_key: str = "basico"
    template_title: str = ""
    template_reason: str = ""
    strength: float = 1.0

    def node(self, role: str) -> NodeSpec:
        return next(n for n in self.nodes if n.role == role)

    def has(self, role: str) -> bool:
        return any(n.role == role for n in self.nodes)

    def as_dict(self) -> dict:
        return {
            "profile": self.profile_key,
            "matcher": self.matcher,
            "template": self.template_key,
            "template_reason": self.template_reason,
            "strength": self.strength,
            "nodes": [n.as_dict() for n in self.nodes],
            "verification": self.verification,
            "warnings": self.warnings,
        }
