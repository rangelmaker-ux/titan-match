from titan_match.engine import analyze
from titan_match.report import format_dry_run
from synth import make_pair


def test_dry_run_has_plain_numbers():
    log, ref = make_pair()
    txt = format_dry_run(analyze(ref, log, "sony_slog3").plan)
    assert "np.float64" not in txt


def test_bundled_template_is_found():
    from titan_match.ui import default_template

    p = default_template()
    assert p is not None and p.suffix == ".drx" and p.stat().st_size > 1000
