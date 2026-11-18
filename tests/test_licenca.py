"""Licença Titan Loja: ativação, revalidação, carência offline e recusa (loja simulada)."""
import pytest

from titan_match import licenca


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(licenca, "license_path", lambda: tmp_path / "licenca.json")
    monkeypatch.setattr(licenca, "ENFORCE_LICENSE", True)


def loja(ok=True, erro="Chave inválida.", calls=None):
    def poster(payload):
        if calls is not None:
            calls.append(payload)
        return {"ok": True, "nome": "Cliente", "expira_em": None} if ok else {"ok": False, "erro": erro}
    return poster


def test_activation_sends_key_device_and_product():
    calls = []
    st = licenca.activate("ABC-123", poster=loja(calls=calls), now=1000)
    assert st.valid and st.nome == "Cliente"
    p = calls[0]
    assert p["acao"] == "ativar" and p["chave"] == "ABC-123" and p["produto"] == "titan-match"
    assert p["dispositivo"].startswith("match-")


def test_invalid_key_is_rejected():
    with pytest.raises(licenca.LicenseError, match="inválida"):
        licenca.activate("XXX", poster=loja(ok=False))


def test_periodic_revalidation_and_offline_grace():
    licenca.activate("ABC", poster=loja(), now=0)
    calls = []
    assert licenca.status(poster=loja(calls=calls), now=10).valid and not calls  # dentro de 3 dias: sem rede

    def offline(_):
        raise OSError("sem internet")
    assert licenca.status(poster=offline, now=licenca.VERIFY_EVERY + 1).valid  # carência
    assert not licenca.status(poster=offline, now=licenca.GRACE + 5).valid  # passou a carência
    assert licenca.status(poster=loja(), now=licenca.GRACE + 10).valid  # voltou a internet


def test_store_revocation_blocks():
    licenca.activate("ABC", poster=loja(), now=0)
    st = licenca.status(poster=loja(ok=False, erro="Chave revogada."), now=licenca.VERIFY_EVERY + 1)
    assert not st.valid and "revogada" in st.reason


def test_not_activated_blocks_only_when_enforced(monkeypatch):
    assert not licenca.status(now=0).valid
    monkeypatch.setattr(licenca, "ENFORCE_LICENSE", False)
    assert licenca.status(now=0).valid
