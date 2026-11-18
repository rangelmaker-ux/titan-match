"""Imprime a conferência simulada para todos os profiles (imagens sintéticas)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from synth import make_pair  # noqa: E402
from titan_match.engine import analyze  # noqa: E402
from titan_match.profiles import PROFILES  # noqa: E402

for k in PROFILES:
    log, ref = make_pair(k)
    v = analyze(ref, log, k).plan.verification
    print(f"{k:15s} hist {v['hist_dist_display_antes']:.4f} -> {v['hist_dist_display_depois']:.4f}   "
          f"dLab medios {v['delta_lab_medios_antes']} -> {v['delta_lab_medios_depois']}")
