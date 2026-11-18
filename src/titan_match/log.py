"""Log local do Titan Match (%LOCALAPPDATA%\\TitanMatch\\Logs\\titan_match.log).

Só registra etapas, erros e resultados de chamadas da API; nunca imagens.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_LOGGER: logging.Logger | None = None


def log_dir() -> Path:
    from .paths import log_dir as _ld

    return _ld()


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    lg = logging.getLogger("titan_match")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(d / "titan_match.log", maxBytes=1_000_000, backupCount=3,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h)
    except OSError:
        lg.addHandler(logging.NullHandler())  # log nunca impede o plugin de funcionar
    _LOGGER = lg
    return lg
