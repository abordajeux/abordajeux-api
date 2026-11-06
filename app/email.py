import html
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from dns import resolver as dns_resolver
from dns.exception import DNSException
from dns.resolver import NXDOMAIN, NoAnswer

MAIL_URL = "https://api.resend.com/emails"
SENDER_NAME = "À L'Abordajeux"
SUBJECT = "Confirmez votre inscription — Presques 24h du Jeu"
WAITLIST_SUBJECT = "Vous êtes sur la liste d'attente — Presques 24h du Jeu"
BENEVOLE_WELCOME_SUBJECT = "Devenir bénévole — À L'Abordajeux"

_FR_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass
class EmailContent:
    subject: str
    html: str
    text: str


def _format_fr(starts_at: datetime) -> tuple[str, str]:
    date_str = f"{starts_at.day} {_FR_MONTHS[starts_at.month - 1]} {starts_at.year}"
    time_str = f"{starts_at.hour:02d}:{starts_at.minute:02d}"
    return date_str, time_str


def _names_line(participant_names: list[str]) -> tuple[str, str]:
    label = ("Personne inscrite"
             if len(participant_names) == 1 else "Personnes inscrites")
    names = ", ".join(participant_names)
    safe_names = ", ".join(html.escape(name) for name in participant_names)
    return f"{label} : {names}.", f"{label} : {safe_names}."


def build_verification_email(
    *,
    activity_title: str,
    starts_at: datetime,
    verify_link: str,
    contact_email: str,
    participant_names: list[str],
) -> EmailContent:
    date_str, time_str = _format_fr(starts_at)
    safe_title = html.escape(activity_title)
    safe_link = html.escape(verify_link)
    safe_contact = html.escape(contact_email)
    names_line, safe_names_line = _names_line(participant_names)

    text = f"""
Chère personne, bonjour,
Vous vous êtes inscrit·e pour {activity_title} lors des presques 24h du jeu. Cette activité aura lieu le {date_str} à {time_str} si des événements fâcheux ne nous font pas modifier l'horaire.
{names_line}
Pour confirmer votre inscription, il sera nécessaire de cliquer sur le lien suivant:
    {verify_link}
Si vous avez la moindre question, ou en cas de désistement, vous pouvez nous contacter à {contact_email}

Ce lien expirera dans 48 heures. Passé ce délai, nous annulerons automatiquement votre inscription.

Nous nous réjouissons de vous accueillir lors des Presques 24 heures.

L'équipage de À L'abordajeux
    """

    body = f"""
<p>Chère personne, bonjour,</p>
<p>Vous vous êtes inscrit·e pour {safe_title} lors des presques 24h du jeu. Cette activité aura lieu
le {date_str} à {time_str} si des événements fâcheux ne nous font pas modifier l'horaire.</p>
<p><b>{safe_names_line}</b></p>
<p><b>Pour confirmer votre inscription</b>, il sera nécessaire de cliquer sur le lien suivant: <a href="{safe_link}">{safe_link}</a></p>
<p>Si vous avez la moindre question, ou en cas de désistement, vous pouvez nous contacter à <a href="mailto:{safe_contact}">{safe_contact}</a></p>

<p><b>Ce lien expirera dans 48 heures. Passé ce délai, nous annulerons automatiquement votre inscription.</b></p>


<p>Nous nous réjouissons de vous accueillir lors des Presques 24 heures.</p>

<p>L'équipage de À L'abordajeux</p>
    """

    return EmailContent(subject=SUBJECT, html=body, text=text)


def build_waitlist_email(
    *,
    activity_title: str,
    starts_at: datetime,
    verify_link: str,
    contact_email: str,
    participant_names: list[str],
) -> EmailContent:
    date_str, time_str = _format_fr(starts_at)
    safe_title = html.escape(activity_title)
    safe_link = html.escape(verify_link)
    safe_contact = html.escape(contact_email)
    names_line, safe_names_line = _names_line(participant_names)

    text = f"""
Chère personne, bonjour,
L'activité {activity_title} du {date_str} à {time_str} est complète : vous avez été ajouté·e à la liste d'attente.
{names_line}
Pour confirmer votre intérêt, il sera nécessaire de cliquer sur le lien suivant:
    {verify_link}
Si une place se libère, nous vous enverrons un email — votre place sera alors réservée automatiquement, sans action de votre part.
Si vous avez la moindre question, vous pouvez nous contacter à {contact_email}

Ce lien expirera dans 48 heures. Passé ce délai, nous annulerons automatiquement votre inscription sur la liste d'attente.

Nous nous réjouissons de vous accueillir lors des Presques 24 heures.

L'équipage de À L'abordajeux
    """

    body = f"""
<p>Chère personne, bonjour,</p>
<p>L'activité {safe_title} du {date_str} à {time_str} est complète : vous avez été ajouté·e à la
liste d'attente.</p>
<p><b>{safe_names_line}</b></p>
<p>Pour confirmer votre intérêt, il sera nécessaire de cliquer sur le lien suivant: <a href="{safe_link}">{safe_link}</a></p>
<p>Si une place se libère, nous vous enverrons un email — votre place sera alors réservée
automatiquement, sans action de votre part.</p>
<p>Si vous avez la moindre question, vous pouvez nous contacter à <a href="mailto:{safe_contact}">{safe_contact}</a></p>

<p>Ce lien expirera dans 48 heures. Passé ce délai, nous annulerons automatiquement votre
inscription sur la liste d'attente.</p>

<p>Nous nous réjouissons de vous accueillir lors des Presques 24 heures.</p>

<p>L'équipage de À L'abordajeux</p>
    """

    return EmailContent(subject=WAITLIST_SUBJECT, html=body, text=text)


def build_promotion_email(
    *,
    activity_title: str,
    starts_at: datetime,
) -> EmailContent:
    date_str, time_str = _format_fr(starts_at)
    safe_title = html.escape(activity_title)
    subject = f"Une place s'est libérée — {activity_title}"

    text = f"""
Chère personne, bonjour,
Bonne nouvelle : une place s'est libérée pour {activity_title} le {date_str} à {time_str}.
Votre place est désormais réservée — aucune action de votre part n'est nécessaire.

Nous nous réjouissons de vous accueillir lors des Presques 24 heures.

L'équipage de À L'abordajeux
    """

    body = f"""
<p>Chère personne, bonjour,</p>
<p>Bonne nouvelle : une place s'est libérée pour {safe_title} le {date_str} à {time_str}.</p>
<p>Votre place est désormais réservée — aucune action de votre part n'est nécessaire.</p>

<p>Nous nous réjouissons de vous accueillir lors des Presques 24 heures.</p>

<p>L'équipage de À L'abordajeux</p>
    """

    return EmailContent(subject=subject, html=body, text=text)


def build_contact_form_email(
    *,
    subject: str,
    sender_email: str,
    message: str,
) -> EmailContent:
    safe_subject = html.escape(subject)
    safe_sender = html.escape(sender_email)
    safe_message = html.escape(message).replace("\n", "<br>")
    full_subject = f"Formulaire de contact — {subject}"

    text = f"""
Nouveau message via le formulaire de contact du site.

Sujet : {subject}
Email : {sender_email}

Message :
{message}
    """

    body = f"""
<p>Nouveau message via le formulaire de contact du site.</p>
<p><strong>Sujet :</strong> {safe_subject}</p>
<p><strong>Email :</strong> <a href="mailto:{safe_sender}">{safe_sender}</a></p>
<p><strong>Message :</strong></p>
<p>{safe_message}</p>
    """

    return EmailContent(subject=full_subject, html=body, text=text)


def build_feedback_form_email(
    *,
    event: str,
    sender_email: str,
    message: str,
    planning_rating: int,
    welcome_rating: int,
) -> EmailContent:
    safe_event = html.escape(event)
    safe_sender = html.escape(sender_email)
    safe_message = html.escape(message).replace("\n", "<br>")
    subject = f"Retour sur un événement — {event}"

    text = f"""
Nouveau retour sur un événement via le formulaire du site.

Événement : {event}
Email : {sender_email}
Accueil : {welcome_rating}/5
Organisation : {planning_rating}/5

Message :
{message}
    """

    body = f"""
<p>Nouveau retour sur un événement via le formulaire du site.</p>
<p><strong>Événement :</strong> {safe_event}</p>
<p><strong>Email :</strong> <a href="mailto:{safe_sender}">{safe_sender}</a></p>
<p><strong>Accueil :</strong> {welcome_rating}/5</p>
<p><strong>Organisation :</strong> {planning_rating}/5</p>
<p><strong>Message :</strong></p>
<p>{safe_message}</p>
    """

    return EmailContent(subject=subject, html=body, text=text)


def build_benevole_welcome_email(
    *,
    coordinator_email: str,
    benevolus_org_link: str,
    benevolus_token: str,
) -> EmailContent:
    safe_coordinator = html.escape(coordinator_email)
    safe_link = html.escape(benevolus_org_link)
    safe_token = html.escape(benevolus_token)

    text = f"""
Chère personne, bonjour,
Tout d'abord, merci de l'intérêt que vous portez aux presque 24h du jeu, et nous nous réjouissons de vous intégrer à l'équipage !

La gestion des bénévoles et des shifts se fera par l'application benevolus. Si, comme la personne qui écrit ce mail, vous faites
partie des gens qui refusent de créer des comptes, il vous faudra contacter notre recruteur de bénévoles afin d'obtenir une exemption
(je vous rassure, c'est plus une formalité, mais plus de personnes utilisent l'application, plus c'est facile pour notre responsable).

Dans le cas contraire, en suivant le lien ci dessous, vous arriverez sur l'application benevolus, et en créant un compte, vous rejoindrez
l'organisation générale. Vous pourrez alors trouver les presques 24h du jeu sous l'onglet "événement".
Une fois sur l'événement, vous pourrez alors choisir vos shifts comme bon vous semble.

Lien : {benevolus_org_link}?token={benevolus_token}

Rejoindre les bénévoles vous donne les avantages suivants:

 - L'entrée est gratuite
 - Chaque shift de 2h s'accompagne de softs à volonté (pour la consommation personelle) pendant la durée de la shift.
 - chaque shift de 4h (ou deux shifts de 2h) donne droit à un repas.

Si vous avez la moindre question, vous pouvez contacter notre recruteur à {coordinator_email}

L'équipage de À L'Abordajeux
"""

    body = f"""
<p>Chère personne, bonjour,</p>
<p>Tout d'abord, merci de l'intérêt que vous portez aux presque 24h du jeu, et nous nous réjouissons de vous intégrer à l'équipage. !</p>

<p>La gestion des bénévoles et des shifts se fera par l'application <strong>benevolus</strong>.
   Si, comme la personne qui écrit ce mail, vous faites partie des gens qui refusent de créer des comptes,
   il vous faudra contacter notre recruteur de bénévoles afin d'obtenir une exemption
   (je vous rassure, c'est plus une formalité, mais plus de personnes utilisent l'application, plus c'est facile pour notre responsable).</p>


<p>Dans le cas contraire, en suivant le lien ci dessous, vous arriverez sur l'application benevolus, et en créant un compte, vous rejoindrez
l'organisation générale. Vous pourrez alors trouver les presques 24h du jeu sous l'onglet "événement".
Une fois sur l'événement, vous pourrez alors choisir vos shifts comme bon vous semble.</p>

<p>Rejoindre les bénévoles vous donne les avantages suivants:</p>

<ul>
<li>L'entrée est gratuite</li>
<li>Chaque shift de 2h s'accompagne de softs à volonté (pour la consommation personelle) pendant la durée de la shift.</li>
<li>chaque shift de 4h (ou deux shifts de 2h) donne droit à un repas.</li>
</ul>

<p><strong>Lien :</strong> <a href="{safe_link}?token={safe_token}">Rejoindre les bénévoles</a></p>

<p>Si vous avez la moindre question, vous pouvez contacter notre recruteur à <a href="mailto:{safe_coordinator}">{safe_coordinator}</a></p>

<p>L'équipage de À L'Abordajeux</p>
    """

    return EmailContent(subject=BENEVOLE_WELCOME_SUBJECT, html=body, text=text)


def build_benevole_notification_email(
    *,
    sender_email: str,
) -> EmailContent:
    safe_sender = html.escape(sender_email)
    subject = f"Nouvelle proposition de bénévolat — {sender_email}"

    text = f"""
Bonjour à toi, recruteur de nos fiers bénévoles.

Une personne souhaite rejoindre l'équipe de bénévoles, et a reçu des instructions pour rejoindre l'équipage.

Email : {sender_email}

Réponds directement à cet email pour prendre contact.
"""

    body = f"""
<p>Bonjour à toi, recruteur de nos fiers bénévoles.</p>
<p>Une personne souhaite rejoindre l'équipe de bénévoles, et a reçu des instructions pour rejoindre l'équipage.</p>
<p><strong>Email :</strong> <a href="mailto:{safe_sender}">{safe_sender}</a></p>
<p>Réponds directement à cet email pour prendre contact.</p>
    """

    return EmailContent(subject=subject, html=body, text=text)


class MailSender(Protocol):

    def send(self,
             *,
             to_email: str,
             content: EmailContent,
             reply_to: str | None = None) -> None:
        ...


class MailSendError(Exception):
    pass


_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_DELAYS = (0.5, 1.0)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return (isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code in _RETRYABLE_STATUSES)


def send_with_retry(
        sender: MailSender,
        *,
        to_email: str,
        content: EmailContent,
        reply_to: str | None = None,
        attempts: int = 3,
        delays: tuple[float, ...] = _RETRY_DELAYS) -> None:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    for attempt in range(attempts):
        if attempt > 0:
            time.sleep(delays[min(attempt - 1, len(delays) - 1)])
        try:
            sender.send(to_email=to_email, content=content, reply_to=reply_to)
            return
        except Exception as exc:
            if not _is_retryable(exc):
                raise MailSendError(str(exc)) from exc
            last_error = exc
    raise MailSendError(str(last_error)) from last_error


class ResendSender:

    def __init__(self, client: httpx.Client, *, api_key: str,
                 sender_email: str, sender_name: str) -> None:
        self._client = client
        self._api_key = api_key
        self._sender_email = sender_email
        self._sender_name = sender_name

    def send(self,
             *,
             to_email: str,
             content: EmailContent,
             reply_to: str | None = None) -> None:
        payload: dict = {
            "from": f"{self._sender_name} <{self._sender_email}>",
            "to": [to_email],
            "subject": content.subject,
            "html": content.html,
            "text": content.text,
        }
        if reply_to is not None:
            payload["reply_to"] = reply_to
        response = self._client.post(
            MAIL_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
        )
        response.raise_for_status()


def split_email(address: str) -> tuple[str, str]:
    if "@" not in address:
        raise ValueError(f"invalid email address: {address!r}")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise ValueError(f"invalid email address: {address!r}")
    return local, domain


def _configured_nameservers() -> list[str]:
    raw = os.environ.get("DNS_RESOLVERS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_resolver() -> dns_resolver.Resolver:
    nameservers = _configured_nameservers()
    resolver = dns_resolver.Resolver(configure=not nameservers)
    if nameservers:
        resolver.nameservers = nameservers
    resolver.timeout = 4.0
    resolver.lifetime = 8.0
    resolver.cache = dns_resolver.Cache()
    return resolver


_resolver = _build_resolver()


def _warn_dns_failure(domain: str, exc: BaseException) -> None:
    print(f"mx lookup failed for {domain!r} ({exc}); accepting domain")


def _address_record_exists(domain: str) -> bool:
    for rdtype in ("A", "AAAA"):
        try:
            _resolver.resolve(domain, rdtype)
            return True
        except NXDOMAIN:
            return False
        except NoAnswer:
            continue
        except DNSException as exc:
            _warn_dns_failure(domain, exc)
            return True
    return False


def mx_records_exist(domain: str) -> bool:
    try:
        _resolver.resolve(domain, "MX")
        return True
    except NXDOMAIN:
        return False
    except NoAnswer:
        return _address_record_exists(domain)
    except (DNSException, ValueError) as exc:
        _warn_dns_failure(domain, exc)
        return True


def has_valid_mx(address: str) -> bool:
    try:
        _, domain = split_email(address)
    except ValueError:
        return False
    return mx_records_exist(domain)
