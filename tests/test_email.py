from datetime import datetime, timedelta, timezone

import httpx
import pytest
from dns.exception import DNSException, Timeout

from app import email

_STARTS_AT = datetime(2026, 11, 14, 10, 0, tzinfo=timezone(timedelta(hours=1)))


class _StubResponse:

    def __init__(self, *, raise_exc: BaseException | None = None) -> None:
        self._raise_exc = raise_exc

    def raise_for_status(self) -> None:
        if self._raise_exc is not None:
            raise self._raise_exc


class _StubClient:

    def __init__(self, *, raise_exc: BaseException | None = None) -> None:
        self.calls: list[tuple] = []
        self._raise_exc = raise_exc

    def post(self,
             url: str,
             headers: dict | None = None,
             json: dict | None = None) -> _StubResponse:
        self.calls.append((url, headers, json))
        return _StubResponse(raise_exc=self._raise_exc)


def test_build_verification_email_contains_required_phrases() -> None:
    content = email.build_verification_email(
        activity_title="D&D — La Mine de Phandelver",
        starts_at=_STARTS_AT,
        verify_link="https://abordajeux.github.io/presque/verify?token=abc",
        contact_email="contact@abordajeux.ch",
    )

    assert content.subject == "Confirmez votre inscription — Presques 24h du Jeu"

    for phrase in (
            "Chère personne, bonjour",
            "D&D — La Mine de Phandelver",
            "14 novembre 2026",
            "10:00",
            "https://abordajeux.github.io/presque/verify?token=abc",
            "contact@abordajeux.ch",
            "expirera dans 24",
            "L'équipage de À L'abordajeux",
    ):
        assert phrase in content.text

    assert "D&amp;D — La Mine de Phandelver" in content.html
    assert 'href="https://abordajeux.github.io/presque/verify?token=abc"' in content.html
    assert 'href="mailto:contact@abordajeux.ch"' in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_verification_email_escapes_html() -> None:
    content = email.build_verification_email(
        activity_title="<script>x</script>",
        starts_at=_STARTS_AT,
        verify_link="https://example/verify?t=a&b=c",
        contact_email="c@example.ch",
    )

    assert "&lt;script&gt;" in content.html
    assert "<script>x</script>" not in content.html
    assert "&amp;b=c" in content.html


def test_build_waitlist_email_contains_required_phrases() -> None:
    content = email.build_waitlist_email(
        activity_title="D&D — La Mine de Phandelver",
        starts_at=_STARTS_AT,
        verify_link="https://abordajeux.github.io/presque/verify?token=abc",
        contact_email="contact@abordajeux.ch",
    )

    assert content.subject == "Vous êtes sur la liste d'attente — Presques 24h du Jeu"

    for phrase in (
            "Chère personne, bonjour",
            "D&D — La Mine de Phandelver",
            "14 novembre 2026",
            "10:00",
            "liste d'attente",
            "https://abordajeux.github.io/presque/verify?token=abc",
            "contact@abordajeux.ch",
            "Si une place se libère",
            "expirera dans 24",
            "L'équipage de À L'abordajeux",
    ):
        assert phrase in content.text

    assert "D&amp;D — La Mine de Phandelver" in content.html
    assert 'href="https://abordajeux.github.io/presque/verify?token=abc"' in content.html
    assert 'href="mailto:contact@abordajeux.ch"' in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_promotion_email_contains_required_phrases() -> None:
    content = email.build_promotion_email(
        activity_title="D&D — La Mine de Phandelver",
        starts_at=_STARTS_AT,
    )

    assert content.subject == "Une place s'est libérée — D&D — La Mine de Phandelver"

    for phrase in (
            "Chère personne, bonjour",
            "Bonne nouvelle : une place s'est libérée",
            "D&D — La Mine de Phandelver",
            "le 14 novembre 2026 à 10:00",
            "désormais réservée",
            "aucune action de votre part",
            "L'équipage de À L'abordajeux",
    ):
        assert phrase in content.text

    assert "D&amp;D — La Mine de Phandelver" in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_waitlist_email_escapes_html() -> None:
    content = email.build_waitlist_email(
        activity_title="<script>x</script>",
        starts_at=_STARTS_AT,
        verify_link="https://example/verify?t=a&b=c",
        contact_email="c@example.ch",
    )

    assert "&lt;script&gt;" in content.html
    assert "<script>x</script>" not in content.html
    assert "&amp;b=c" in content.html


def test_mail_sender_posts_to_brevo() -> None:
    client = _StubClient()
    sender = email.BrevoSender(
        client,  # type: ignore[arg-type]  # test stub replaces the injected httpx.Client (no network)
        api_key="key-123",
        sender_email="noreply@abordajeux.ch",
        sender_name="À L'Abordajeux",
    )
    content = email.EmailContent(subject="s", html="<p>h</p>", text="t")

    sender.send(to_email="player@example.com", content=content)

    assert len(client.calls) == 1
    url, headers, body = client.calls[0]
    assert url == email.MAIL_URL
    assert headers["api-key"] == "key-123"
    assert body["sender"] == {
        "name": "À L'Abordajeux",
        "email": "noreply@abordajeux.ch"
    }
    assert body["to"] == [{"email": "player@example.com"}]
    assert body["subject"] == "s"
    assert body["htmlContent"] == "<p>h</p>"
    assert body["textContent"] == "t"


def test_mail_sender_propagates_http_errors() -> None:
    request = httpx.Request("POST", email.MAIL_URL)
    response = httpx.Response(500, request=request)
    client = _StubClient(raise_exc=httpx.HTTPStatusError(
        "boom", request=request, response=response))
    sender = email.BrevoSender(
        client,  # type: ignore[arg-type]  # test stub replaces the injected httpx.Client (no network)
        api_key="k",
        sender_email="noreply@abordajeux.ch",
        sender_name="À L'Abordajeux",
    )

    with pytest.raises(httpx.HTTPStatusError):
        sender.send(
            to_email="player@example.com",
            content=email.EmailContent(subject="s", html="h", text="t"),
        )


def test_mx_records_exist_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email._resolver, "resolve",
                        lambda *a, **k: ["mx1.example.com"])
    assert email.mx_records_exist("example.com") is True


def test_mx_records_exist_false_on_dns_failure(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise DNSException("no mx")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.mx_records_exist("gmaill.com") is False


def test_mx_records_exist_false_on_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise Timeout("dns slow")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.mx_records_exist("slow.example.com") is False


def test_has_valid_mx_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email._resolver, "resolve",
                        lambda *a, **k: ["mx1.example.com"])
    assert email.has_valid_mx("player@example.com") is True


def test_has_valid_mx_false_when_no_mx(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise DNSException("no mx")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.has_valid_mx("player@gmaill.com") is False


def test_has_valid_mx_false_for_invalid_address(
        monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def _fail(*a: object, **k: object) -> None:
        called["n"] += 1

    monkeypatch.setattr(email._resolver, "resolve", _fail)
    assert email.has_valid_mx("not-an-email") is False
    assert called["n"] == 0


def test_split_email_invalid() -> None:
    with pytest.raises(ValueError):
        email.split_email("noatsign")
    with pytest.raises(ValueError):
        email.split_email("a@b")
