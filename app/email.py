import html
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx
from dns import resolver as dns_resolver
from dns.exception import DNSException

MAIL_URL = "https://api.brevo.com/v3/smtp/email"
SENDER_NAME = "À L'Abordajeux"
SUBJECT = "Confirmez votre inscription — Presques 24h du Jeu"
WAITLIST_SUBJECT = "Vous êtes sur la liste d'attente — Presques 24h du Jeu"

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


def build_verification_email(
    *,
    activity_title: str,
    starts_at: datetime,
    verify_link: str,
    contact_email: str,
) -> EmailContent:
    date_str, time_str = _format_fr(starts_at)
    safe_title = html.escape(activity_title)
    safe_link = html.escape(verify_link)
    safe_contact = html.escape(contact_email)

    text = f"""
Chère personne, bonjour,
Vous vous êtes inscrit·e pour {activity_title} lors des presques 24h du jeu. Cette activité aura lieu le {date_str} à {time_str} si des événements fâcheux ne nous font pas modifier l'horaire.
Pour confirmer votre inscription, il sera nécessaire de cliquer sur le lien suivant:
    {verify_link}
Si vous avez la moindre question, vous pouvez nous contacter à {contact_email}

Ce lien expirera dans 24 heures. Passé ce délai, nous annulerons automatiquement votre inscription.

Nous nous réjouissons de vous accueillir lors des Presques 24 heures.

L'équipage de À L'abordajeux
    """

    body = f"""
<p>Chère personne, bonjour,</p>
<p>Vous vous êtes inscrit·e pour {safe_title} lors des presques 24h du jeu. Cette activité aura lieu
le {date_str} à {time_str} si des événements fâcheux ne nous font pas modifier l'horaire.</p>
<p>Pour confirmer votre inscription, il sera nécessaire de cliquer sur le lien suivant: <a href="{safe_link}">{safe_link}</a></p>
<p>Si vous avez la moindre question, vous pouvez nous contacter à <a href="mailto:{safe_contact}">{safe_contact}</a></p>

<p>Ce lien expirera dans 24 heures. Passé ce délai, nous annulerons automatiquement votre inscription.</p>

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
) -> EmailContent:
    date_str, time_str = _format_fr(starts_at)
    safe_title = html.escape(activity_title)
    safe_link = html.escape(verify_link)
    safe_contact = html.escape(contact_email)

    text = f"""
Chère personne, bonjour,
L'activité {activity_title} du {date_str} à {time_str} est complète : vous avez été ajouté·e à la liste d'attente.
Pour confirmer votre intérêt, il sera nécessaire de cliquer sur le lien suivant:
    {verify_link}
Si une place se libère, nous vous enverrons un email — votre place sera alors réservée automatiquement, sans action de votre part.
Si vous avez la moindre question, vous pouvez nous contacter à {contact_email}

Ce lien expirera dans 24 heures. Passé ce délai, nous annulerons automatiquement votre inscription sur la liste d'attente.

Nous nous réjouissons de vous accueillir lors des Presques 24 heures.

L'équipage de À L'abordajeux
    """

    body = f"""
<p>Chère personne, bonjour,</p>
<p>L'activité {safe_title} du {date_str} à {time_str} est complète : vous avez été ajouté·e à la
liste d'attente.</p>
<p>Pour confirmer votre intérêt, il sera nécessaire de cliquer sur le lien suivant: <a href="{safe_link}">{safe_link}</a></p>
<p>Si une place se libère, nous vous enverrons un email — votre place sera alors réservée
automatiquement, sans action de votre part.</p>
<p>Si vous avez la moindre question, vous pouvez nous contacter à <a href="mailto:{safe_contact}">{safe_contact}</a></p>

<p>Ce lien expirera dans 24 heures. Passé ce délai, nous annulerons automatiquement votre
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


class MailSender(Protocol):

    def send(self, *, to_email: str, content: EmailContent) -> None:
        ...


class BrevoSender:

    def __init__(self, client: httpx.Client, *, api_key: str,
                 sender_email: str, sender_name: str) -> None:
        self._client = client
        self._api_key = api_key
        self._sender_email = sender_email
        self._sender_name = sender_name

    def send(self, *, to_email: str, content: EmailContent) -> None:
        response = self._client.post(
            MAIL_URL,
            headers={
                "api-key": self._api_key,
                "Content-Type": "application/json"
            },
            json={
                "sender": {
                    "name": self._sender_name,
                    "email": self._sender_email
                },
                "to": [{
                    "email": to_email
                }],
                "subject": content.subject,
                "htmlContent": content.html,
                "textContent": content.text,
            },
        )
        response.raise_for_status()


def split_email(address: str) -> tuple[str, str]:
    if "@" not in address:
        raise ValueError(f"invalid email address: {address!r}")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or "." not in domain:
        raise ValueError(f"invalid email address: {address!r}")
    return local, domain


_resolver = dns_resolver.Resolver()
_resolver.timeout = 4.0
_resolver.lifetime = 8.0
_resolver.cache = dns_resolver.Cache()


def mx_records_exist(domain: str) -> bool:
    try:
        _resolver.resolve(domain, "MX")
    except (DNSException, ValueError):
        return False
    return True


def has_valid_mx(address: str) -> bool:
    try:
        _, domain = split_email(address)
    except ValueError:
        return False
    return mx_records_exist(domain)
