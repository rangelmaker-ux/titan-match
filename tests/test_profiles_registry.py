from titan_match import profiles as pf


def test_every_brand_requested_is_covered():
    for brand in ["Sony", "Canon", "Panasonic Lumix", "Fujifilm", "Nikon", "DJI", "GoPro", "Apple",
                  "Leica", "Blackmagic", "ARRI", "RED"]:
        assert pf.profiles_for_brand(brand), brand


def test_existing_profile_keys_are_stable():
    for key in ["sony_slog3", "panasonic_vlog", "canon_clog3", "red_log3g10", "arri_logc3",
                "bmd_film_gen5", "dji_dlog", "rec709"]:
        assert key in pf.PROFILES


def test_every_profile_gamut_exists():
    from titan_match import colorspaces as cs

    for p in pf.PROFILES.values():
        assert p.gamut in cs.GAMUTS, p.key
