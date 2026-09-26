import pytest
from pydantic import ValidationError

from app.schemas import (
    BenevoleFormRequest,
    ContactFormRequest,
    FeedbackFormRequest,
    sanitize_line,
    sanitize_message,
)

_CONTACT_BODY = {
    "subject": "Question sur les Presques 24h",
    "sender_email": "visitor@example.com",
    "message": "Bonjour, une question ?",
}

_FEEDBACK_BODY = {
    "event": "Soirée jeu du mercredi",
    "sender_email": "visitor@example.com",
    "message": "Super soirée !",
    "planning_rating": 4,
    "welcome_rating": 5,
}


def test_sanitize_line_strips_control_chars() -> None:
    assert sanitize_line("a\r\nb\x00c\td\x7fe\x9bf") == "abcdef"


def test_sanitize_message_keeps_newlines_and_tabs() -> None:
    assert sanitize_message("a\nb\tc\r\x00d\x01e") == "a\nb\tcde"


def test_contact_form_accepts_valid_body() -> None:
    form = ContactFormRequest(**_CONTACT_BODY)
    assert form.subject == _CONTACT_BODY["subject"]
    assert str(form.sender_email) == "visitor@example.com"


def test_contact_form_strips_control_chars_from_subject() -> None:
    body = {**_CONTACT_BODY, "subject": "Bonjour\r\nBcc: evil@example.com"}
    form = ContactFormRequest(**body)
    assert form.subject == "BonjourBcc: evil@example.com"


def test_contact_form_strips_null_bytes_from_message() -> None:
    body = {**_CONTACT_BODY, "message": "ligne 1\n\x00ligne 2"}
    form = ContactFormRequest(**body)
    assert form.message == "ligne 1\nligne 2"


def test_contact_form_rejects_control_only_subject() -> None:
    body = {**_CONTACT_BODY, "subject": "\x01\x02"}
    with pytest.raises(ValidationError):
        ContactFormRequest(**body)


def test_contact_form_rejects_bad_email() -> None:
    body = {**_CONTACT_BODY, "sender_email": "not-an-email"}
    with pytest.raises(ValidationError):
        ContactFormRequest(**body)


def test_contact_form_rejects_empty_and_overlong_fields() -> None:
    with pytest.raises(ValidationError):
        ContactFormRequest(**{**_CONTACT_BODY, "subject": "  "})
    with pytest.raises(ValidationError):
        ContactFormRequest(**{**_CONTACT_BODY, "subject": "x" * 201})
    with pytest.raises(ValidationError):
        ContactFormRequest(**{**_CONTACT_BODY, "message": ""})
    with pytest.raises(ValidationError):
        ContactFormRequest(**{**_CONTACT_BODY, "message": "x" * 5001})


def test_feedback_form_accepts_valid_body() -> None:
    form = FeedbackFormRequest(**_FEEDBACK_BODY)
    assert (form.planning_rating, form.welcome_rating) == (4, 5)


def test_feedback_form_strips_control_chars_from_event() -> None:
    body = {**_FEEDBACK_BODY, "event": "NIFFF\r\n 2026"}
    form = FeedbackFormRequest(**body)
    assert form.event == "NIFFF 2026"


def test_feedback_form_rejects_out_of_range_ratings() -> None:
    with pytest.raises(ValidationError):
        FeedbackFormRequest(**{**_FEEDBACK_BODY, "planning_rating": 6})
    with pytest.raises(ValidationError):
        FeedbackFormRequest(**{**_FEEDBACK_BODY, "welcome_rating": -1})


def test_benevole_form_accepts_valid_body() -> None:
    form = BenevoleFormRequest(sender_email="visitor@example.com")
    assert str(form.sender_email) == "visitor@example.com"


def test_benevole_form_strips_surrounding_whitespace() -> None:
    form = BenevoleFormRequest(sender_email="  visitor@example.com  ")
    assert str(form.sender_email) == "visitor@example.com"


def test_benevole_form_rejects_bad_email() -> None:
    with pytest.raises(ValidationError):
        BenevoleFormRequest(sender_email="not-an-email")


def test_benevole_form_rejects_missing_email() -> None:
    with pytest.raises(ValidationError):
        BenevoleFormRequest()
