from .base import Matcher, MatchOptions, MatchResult, available_matchers, get_matcher, register
from . import statistical  # noqa: F401  (registra o matcher padrão)

__all__ = ["Matcher", "MatchOptions", "MatchResult", "available_matchers", "get_matcher", "register"]
