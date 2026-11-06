from datetime import datetime, timedelta, timezone

import httpx
import pytest
from dns.exception import DNSException, Timeout
from dns.resolver import NXDOMAIN, NoAnswer, NoNameservers

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
        participant_names=["Alice", "Bob"],
    )

    assert content.subject == "Confirmez votre inscription — Presques 24h du Jeu"

    for phrase in (
            "Chère personne, bonjour",
            "D&D — La Mine de Phandelver",
            "14 novembre 2026",
            "10:00",
            "Personnes inscrites : Alice, Bob.",
            "https://abordajeux.github.io/presque/verify?token=abc",
            "contact@abordajeux.ch",
            "expirera dans 48",
            "L'équipage de À L'abordajeux",
    ):
        assert phrase in content.text

    assert "D&amp;D — La Mine de Phandelver" in content.html
    assert "Personnes inscrites : Alice, Bob." in content.html
    assert 'href="https://abordajeux.github.io/presque/verify?token=abc"' in content.html
    assert 'href="mailto:contact@abordajeux.ch"' in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_verification_email_escapes_html() -> None:
    content = email.build_verification_email(
        activity_title="<script>x</script>",
        starts_at=_STARTS_AT,
        verify_link="https://example/verify?t=a&b=c",
        contact_email="c@example.ch",
        participant_names=["<i>Alice</i> & Bob"],
    )

    assert "&lt;script&gt;" in content.html
    assert "<script>x</script>" not in content.html
    assert "&amp;b=c" in content.html
    assert "&lt;i&gt;Alice&lt;/i&gt; &amp; Bob" in content.html
    assert "<i>Alice</i>" not in content.html


def test_build_waitlist_email_contains_required_phrases() -> None:
    content = email.build_waitlist_email(
        activity_title="D&D — La Mine de Phandelver",
        starts_at=_STARTS_AT,
        verify_link="https://abordajeux.github.io/presque/verify?token=abc",
        contact_email="contact@abordajeux.ch",
        participant_names=["Alice"],
    )

    assert content.subject == "Vous êtes sur la liste d'attente — Presques 24h du Jeu"

    for phrase in (
            "Chère personne, bonjour",
            "D&D — La Mine de Phandelver",
            "14 novembre 2026",
            "10:00",
            "liste d'attente",
            "Personne inscrite : Alice.",
            "https://abordajeux.github.io/presque/verify?token=abc",
            "contact@abordajeux.ch",
            "Si une place se libère",
            "expirera dans 48",
            "L'équipage de À L'abordajeux",
    ):
        assert phrase in content.text

    assert "D&amp;D — La Mine de Phandelver" in content.html
    assert "Personne inscrite : Alice." in content.html
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
        participant_names=["<i>Alice</i>"],
    )

    assert "&lt;script&gt;" in content.html
    assert "<script>x</script>" not in content.html
    assert "&amp;b=c" in content.html
    assert "&lt;i&gt;Alice&lt;/i&gt;" in content.html


def test_build_contact_form_email_contains_fields() -> None:
    content = email.build_contact_form_email(
        subject="Question sur les Presques 24h",
        sender_email="visitor@example.com",
        message="Bonjour,\nEst-ce que le programme est définitif ?",
    )

    assert content.subject == "Formulaire de contact — Question sur les Presques 24h"

    for phrase in (
            "Nouveau message via le formulaire de contact",
            "Sujet : Question sur les Presques 24h",
            "Email : visitor@example.com",
            "Est-ce que le programme est définitif ?",
    ):
        assert phrase in content.text

    assert "Question sur les Presques 24h" in content.html
    assert 'href="mailto:visitor@example.com"' in content.html
    assert "Bonjour,<br>Est-ce que le programme est définitif ?" in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_contact_form_email_escapes_html() -> None:
    content = email.build_contact_form_email(
        subject="<script>s</script>",
        sender_email="v@example.ch",
        message="<b>bold</b> & more",
    )

    assert "&lt;script&gt;s&lt;/script&gt;" in content.html
    assert "<script>" not in content.html
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; more" in content.html
    assert "<b>bold</b>" not in content.html


def test_build_feedback_form_email_contains_fields() -> None:
    content = email.build_feedback_form_email(
        event="Soirée jeu du mercredi",
        sender_email="visitor@example.com",
        message="Super soirée, merci !",
        planning_rating=4,
        welcome_rating=5,
    )

    assert content.subject == "Retour sur un événement — Soirée jeu du mercredi"

    for phrase in (
            "Nouveau retour sur un événement",
            "Événement : Soirée jeu du mercredi",
            "Email : visitor@example.com",
            "Accueil : 5/5",
            "Organisation : 4/5",
            "Super soirée, merci !",
    ):
        assert phrase in content.text

    assert "Soirée jeu du mercredi" in content.html
    assert "Accueil :</strong> 5/5" in content.html
    assert "Organisation :</strong> 4/5" in content.html
    assert content.html.count("<p>") == content.html.count("</p>")


def test_build_feedback_form_email_escapes_html() -> None:
    content = email.build_feedback_form_email(
        event="<i>event</i>",
        sender_email="v@example.ch",
        message="<script>m</script>",
        planning_rating=1,
        welcome_rating=2,
    )

    assert "&lt;i&gt;event&lt;/i&gt;" in content.html
    assert "&lt;script&gt;m&lt;/script&gt;" in content.html
    assert "<script>" not in content.html


def test_mail_sender_posts_to_resend() -> None:
    client = _StubClient()
    sender = email.ResendSender(
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
    assert headers["Authorization"] == "Bearer key-123"
    assert body["from"] == "À L'Abordajeux <noreply@abordajeux.ch>"
    assert body["to"] == ["player@example.com"]
    assert body["subject"] == "s"
    assert body["html"] == "<p>h</p>"
    assert body["text"] == "t"
    assert "reply_to" not in body


def test_mail_sender_includes_reply_to_when_given() -> None:
    client = _StubClient()
    sender = email.ResendSender(
        client,  # type: ignore[arg-type]  # test stub replaces the injected httpx.Client (no network)
        api_key="key-123",
        sender_email="noreply@abordajeux.ch",
        sender_name="À L'Abordajeux",
    )

    sender.send(
        to_email="contact@abordajeux.ch",
        content=email.EmailContent(subject="s", html="h", text="t"),
        reply_to="visitor@example.com",
    )

    _, _, body = client.calls[0]
    assert body["reply_to"] == "visitor@example.com"


def test_mail_sender_propagates_http_errors() -> None:
    request = httpx.Request("POST", email.MAIL_URL)
    response = httpx.Response(500, request=request)
    client = _StubClient(raise_exc=httpx.HTTPStatusError(
        "boom", request=request, response=response))
    sender = email.ResendSender(
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


class _FlakySender:

    def __init__(self, errors: list[BaseException]) -> None:
        self._errors = list(errors)
        self.calls = 0

    def send(self,
             *,
             to_email: str,
             content: email.EmailContent,
             reply_to: str | None = None) -> None:
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)


def _status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", email.MAIL_URL)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_send_with_retry_succeeds_after_transient_failure() -> None:
    sender = _FlakySender([httpx.ConnectError("name resolution failed")])

    email.send_with_retry(sender,
                          to_email="player@example.com",
                          content=email.EmailContent(subject="s", html="h", text="t"),
                          delays=(0.0, ))

    assert sender.calls == 2


def test_send_with_retry_exhausts_attempts() -> None:
    sender = _FlakySender([
        httpx.ConnectError("boom 1"),
        httpx.ConnectError("boom 2"),
        httpx.ConnectError("boom 3"),
        httpx.ConnectError("boom 4"),
    ])

    with pytest.raises(email.MailSendError):
        email.send_with_retry(sender,
                              to_email="player@example.com",
                              content=email.EmailContent(subject="s", html="h", text="t"),
                              delays=(0.0, 0.0))

    assert sender.calls == 3


def test_send_with_retry_fails_fast_on_permanent_error() -> None:
    sender = _FlakySender([_status_error(422)])

    with pytest.raises(email.MailSendError):
        email.send_with_retry(sender,
                              to_email="player@example.com",
                              content=email.EmailContent(subject="s", html="h", text="t"),
                              delays=(0.0, 0.0))

    assert sender.calls == 1


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_send_with_retry_retries_retryable_status(status_code: int) -> None:
    sender = _FlakySender([_status_error(status_code)])

    email.send_with_retry(sender,
                          to_email="player@example.com",
                          content=email.EmailContent(subject="s", html="h", text="t"),
                          delays=(0.0, ))

    assert sender.calls == 2


def test_send_with_retry_rejects_zero_attempts() -> None:
    sender = _FlakySender([])

    with pytest.raises(ValueError):
        email.send_with_retry(sender,
                              to_email="player@example.com",
                              content=email.EmailContent(subject="s", html="h", text="t"),
                              attempts=0)


def test_mx_records_exist_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email._resolver, "resolve",
                        lambda *a, **k: ["mx1.example.com"])
    assert email.mx_records_exist("example.com") is True


def test_mx_records_exist_false_on_nxdomain(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise NXDOMAIN("domain does not exist")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.mx_records_exist("gmaill.com") is False


def test_mx_records_exist_true_on_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise Timeout("dns slow")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.mx_records_exist("slow.example.com") is True


def test_mx_records_exist_true_on_resolver_failure(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise NoNameservers("all resolvers refused")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.mx_records_exist("broken.example.com") is True


def test_mx_records_exist_true_on_implicit_mx(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _resolve(domain: str, rdtype: str) -> list[str]:
        calls.append(rdtype)
        if rdtype == "MX":
            raise NoAnswer("no mx")
        return ["192.0.2.10"]

    monkeypatch.setattr(email._resolver, "resolve", _resolve)
    assert email.mx_records_exist("a-only.example.com") is True
    assert calls == ["MX", "A"]


def test_mx_records_exist_false_without_any_record(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _resolve(domain: str, rdtype: str) -> list[str]:
        calls.append(rdtype)
        raise NoAnswer(f"no {rdtype}")

    monkeypatch.setattr(email._resolver, "resolve", _resolve)
    assert email.mx_records_exist("empty.example.com") is False
    assert calls == ["MX", "A", "AAAA"]


def test_mx_records_exist_false_when_address_lookup_nxdomain(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _resolve(domain: str, rdtype: str) -> list[str]:
        if rdtype == "MX":
            raise NoAnswer("no mx")
        raise NXDOMAIN("domain does not exist")

    monkeypatch.setattr(email._resolver, "resolve", _resolve)
    assert email.mx_records_exist("vanishing.example.com") is False


def test_has_valid_mx_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email._resolver, "resolve",
                        lambda *a, **k: ["mx1.example.com"])
    assert email.has_valid_mx("player@example.com") is True


def test_has_valid_mx_false_when_domain_absent(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise NXDOMAIN("domain does not exist")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.has_valid_mx("player@gmaill.com") is False


def test_has_valid_mx_true_when_dns_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:

    def _raise(*args: object, **kwargs: object) -> None:
        raise DNSException("resolver outage")

    monkeypatch.setattr(email._resolver, "resolve", _raise)
    assert email.has_valid_mx("player@example.com") is True


def test_has_valid_mx_false_for_invalid_address(
        monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def _fail(*a: object, **k: object) -> None:
        called["n"] += 1

    monkeypatch.setattr(email._resolver, "resolve", _fail)
    assert email.has_valid_mx("not-an-email") is False
    assert called["n"] == 0


def test_configured_nameservers_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DNS_RESOLVERS", raising=False)
    assert email._configured_nameservers() == []


def test_configured_nameservers_from_env(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DNS_RESOLVERS", " 1.1.1.1 , 8.8.8.8,")
    assert email._configured_nameservers() == ["1.1.1.1", "8.8.8.8"]


def test_build_resolver_uses_configured_nameservers(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DNS_RESOLVERS", "1.1.1.1,8.8.8.8")
    resolver = email._build_resolver()
    assert resolver.nameservers == ["1.1.1.1", "8.8.8.8"]
    assert resolver.timeout == 4.0
    assert resolver.lifetime == 8.0


def test_split_email_invalid() -> None:
    with pytest.raises(ValueError):
        email.split_email("noatsign")
    with pytest.raises(ValueError):
        email.split_email("a@b")
