"""Licença Titan Loja: /api/ativar, /api/licenca, carência offline, recusa e vencimento (loja simulada)."""
import hashlib

import pytest

from titan_match import licenca

VENCE = "2027-11-18T00:00:00.000Z"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(licenca, "license_path", lambda: tmp_path / "licenca.json")
    monkeypatch.setattr(licenca, "ENFORCE_LICENSE", True)


def loja(code=200, erro="Chave inválida.", calls=None, valida_ate=VENCE):
    def poster(rota, payload):
        if calls is not None:
            calls.append((rota, payload))
        if code == 200:
            return 200, {"ok": True, "valida_ate": valida_ate, "atualizacoes": True}
        return code, {"erro": erro}
    return poster


def test_activation_uses_store_ativar_with_product_match():
    calls = []
    st = licenca.activate(" titan-abcd-efgh ", poster=loja(calls=calls), now=1000)
    assert st.valid and st.atualizacoes and st.expira_em
    rota, p = calls[0]
    assert rota == "ativar" and p["produto"] == "match" and p["chave"] == "TITAN-ABCD-EFGH"
    assert p["dispositivo"].startswith("match-")
    saved = licenca._load()
    assert "chave" not in saved and saved["hash"] == hashlib.sha256(b"TITAN-ABCD-EFGH").hexdigest()


def test_store_errors_are_shown():
    with pytest.raises(licenca.LicenseError, match="inválida"):
        licenca.activate("XXX", poster=loja(code=403))
    with pytest.raises(licenca.LicenseError, match="outro computador"):
        licenca.activate("XXX", poster=loja(code=409, erro="Chave já ativada em outro computador."))


def test_revalidation_sends_hash_and_offline_grace():
    licenca.activate("ABC", poster=loja(), now=0)
    calls = []
    assert licenca.status(poster=loja(calls=calls), now=10).valid and not calls  # dentro de 3 dias: sem rede
    licenca.status(poster=loja(calls=calls), now=licenca.VERIFY_EVERY + 1)
    rota, p = calls[0]
    assert rota == "licenca" and p["hash"] == licenca.key_hash("abc") and p["produto"] == "match"

    def offline(*_):
        raise OSError("sem internet")
    t0 = licenca.VERIFY_EVERY + 1
    assert licenca.status(poster=offline, now=t0 + licenca.VERIFY_EVERY).valid  # carência
    assert not licenca.status(poster=offline, now=t0 + licenca.GRACE + 5).valid  # passou a carência
    assert licenca.status(poster=loja(), now=t0 + licenca.GRACE + 10).valid  # voltou a internet


def test_store_block_or_release_stops_the_plugin():
    licenca.activate("ABC", poster=loja(), now=0)
    st = licenca.status(poster=loja(code=403, erro="Chave inválida."), now=licenca.VERIFY_EVERY + 1)
    assert not st.valid and "inválida" in st.reason
    st = licenca.status(poster=loja(code=409, erro="Chave não está ativa neste computador."),
                        now=licenca.VERIFY_EVERY + 2)
    assert not st.valid


def test_expired_license_keeps_working_without_updates():
    licenca.activate("ABC", poster=loja(valida_ate="1970-01-02T00:00:00Z"), now=0)
    venc = 86400
    assert licenca.status(now=venc + 3 * 86400, online=False).atualizacoes  # dentro da espera de 7 dias
    st = licenca.status(now=venc + 8 * 86400, online=False)
    assert st.valid and not st.atualizacoes and "vencida" in st.reason


def test_not_activated_blocks_only_when_enforced(monkeypatch):
    assert not licenca.status(now=0).valid
    monkeypatch.setattr(licenca, "ENFORCE_LICENSE", False)
    assert licenca.status(now=0).valid


def test_trial_key_is_cut_off_right_after_expiry_even_offline():
    def loja_teste(rota, payload):
        return 200, {"ok": True, "valida_ate": "1970-01-04T00:00:00Z", "teste": True}
    st = licenca.activate("TITAN-TEST", poster=loja_teste, now=0)
    assert st.valid and "Teste grátis" in st.reason
    fim = 3 * 86400
    assert licenca.status(now=fim - 60, online=False).valid
    st = licenca.status(now=fim + 60, online=False)
    assert not st.valid and "terminou" in st.reason and "Titan Loja" in st.reason


def test_store_402_ends_trial():
    licenca.activate("ABC", poster=loja(), now=0)
    st = licenca.status(poster=loja(code=402, erro="Seu teste grátis de 3 dias terminou."), now=licenca.VERIFY_EVERY + 1)
    assert not st.valid and "terminou" in st.reason


def test_ssl_context_carrega_certificados():
    from titan_match.net import ssl_context

    ctx = ssl_context()
    assert ctx.verify_mode.name == "CERT_REQUIRED" and ctx.cert_store_stats()["x509_ca"] > 0


def test_erro_de_certificado_tem_mensagem_propria(monkeypatch, tmp_path):
    import ssl
    import urllib.error

    from titan_match import licenca

    def falha(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))

    monkeypatch.setattr(licenca.urllib.request, "urlopen", falha)
    with pytest.raises(licenca.LicenseError, match="certificado"):
        licenca.activate("TITAN-ABCD-1234")
