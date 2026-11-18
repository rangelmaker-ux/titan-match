"""Interface plugável de matching.

Qualquer implementação (estatística hoje, ML amanhã) recebe o footage já
no espaço de trabalho (depois do Input CST) e as estatísticas da referência
no mesmo espaço, e devolve uma correção por nó (02–09). O resto do sistema
(nós, LUTs, dry-run, escrita no Resolve, conferência) não muda.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from ..nodes import CORRECTION_ROLES, NodeCorrection
from ..stats import ImageStats


@dataclass
class MatchOptions:
    film_emulation: bool = False
    strength: float = 1.0  # 0..1: força do match (escala cada CDL em direção à identidade)
    protect_skin: bool = True  # nó SKIN devolve a pele ao tom natural (se o template tiver)
    separate_skin: bool = True  # estatísticas de entorno ignoram a pele
    template: str = "auto"  # "auto" ou chave de template
    haze: str = "auto"  # neblina/fumaça: "auto" (detecta na referência), "on" ou "off"
    skin_ambience: float = 0.35  # quanto da cor do ambiente a pele recebe (0 = original, 1 = igual ao resto)
    source_exclude: np.ndarray | None = None  # preenchido pelo engine (máscara de pele do footage)
    progress: object = None  # callable(pct: float, msg: str) ou None

    def report(self, pct: float, msg: str) -> None:
        if callable(self.progress):
            try:
                self.progress(pct, msg)
            except Exception:  # noqa: BLE001  (progresso nunca derruba a análise)
                pass


@dataclass
class MatchResult:
    corrections: dict[str, NodeCorrection]
    matcher: str
    diagnostics: dict = field(default_factory=dict)

    def validate(self) -> None:
        missing = [r for r in CORRECTION_ROLES if r not in self.corrections]
        if missing:
            raise ValueError(f"Matcher não devolveu correção para: {missing}")
        for role, c in self.corrections.items():
            if c.role != role:
                raise ValueError(f"Correção {c.role!r} registrada como {role!r}")
            if not c.cdl.is_identity() and not c.provenance:
                raise ValueError(f"Nó {role!r} tem valores sem origem registrada")


class Matcher(ABC):
    name: str = "abstract"

    @abstractmethod
    def match(self, source_working: np.ndarray, reference: ImageStats, options: MatchOptions) -> MatchResult:
        ...


_REGISTRY: dict[str, type[Matcher]] = {}


def register(cls: type[Matcher]) -> type[Matcher]:
    _REGISTRY[cls.name] = cls
    return cls


def get_matcher(name: str = "statistical_zone_lab") -> Matcher:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(f"Matcher desconhecido {name!r}; disponíveis: {list(_REGISTRY)}") from None


def available_matchers() -> list[str]:
    return list(_REGISTRY)
