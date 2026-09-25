import asyncio

from app.middleware import BodySizeLimitMiddleware

_CONTACT_BODY = {
    "subject": "x" * 70000,
    "sender_email": "visitor@example.com",
    "message": "hello",
}


def test_oversized_body_rejected_with_413(api) -> None:
    _, client, stub = api

    response = client.post("/forms/contact", json=_CONTACT_BODY)

    assert response.status_code == 413
    body = response.json()
    assert body["status"] == "payload_too_large"
    assert "volumineuse" in body["message"]
    assert stub.calls == []


def test_oversized_signup_rejected_before_capacity_logic(api) -> None:
    _, client, stub = api

    response = client.post(
        "/activities/a1/signup",
        json={
            "contact_email": "player@example.com",
            "participants": [{"name": "x" * 70000}],
        })

    assert response.status_code == 413
    assert response.json()["status"] == "payload_too_large"
    assert stub.calls == []


def _make_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "asgi": {
            "version": "3.0"
        },
        "method": "POST",
        "path": "/forms/contact",
        "headers": headers,
    }


def test_content_length_over_cap_rejected_before_app() -> None:
    app_calls = {"n": 0}

    async def inner_app(scope, receive, send) -> None:
        app_calls["n"] += 1

    async def receive() -> dict:
        raise AssertionError("receive must not be awaited")

    sent = []

    async def send(message) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(inner_app, max_body_bytes=65536)

    asyncio.run(
        middleware(_make_scope([(b"content-length", b"70000")]), receive,
                   send))

    assert app_calls["n"] == 0
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert any(h == (b"content-type", b"application/json")
               for h in sent[0]["headers"])


def test_chunked_body_aborts_when_limit_exceeded() -> None:
    app_calls = {"n": 0}

    async def inner_app(scope, receive, send) -> None:
        app_calls["n"] += 1
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break

    messages = [
        {
            "type": "http.request",
            "body": b"a" * 40000,
            "more_body": True
        },
        {
            "type": "http.request",
            "body": b"b" * 40000,
            "more_body": False
        },
    ]

    async def receive() -> dict:
        return messages.pop(0)

    sent = []

    async def send(message) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(inner_app, max_body_bytes=65536)

    asyncio.run(middleware(_make_scope([]), receive, send))

    assert app_calls["n"] == 1
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_chunked_body_under_limit_passes_through() -> None:
    app_calls = {"n": 0}
    bodies = []

    async def inner_app(scope, receive, send) -> None:
        app_calls["n"] += 1
        while True:
            message = await receive()
            bodies.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

    messages = [
        {
            "type": "http.request",
            "body": b"a" * 40000,
            "more_body": True
        },
        {
            "type": "http.request",
            "body": b"b" * 20000,
            "more_body": False
        },
    ]

    async def receive() -> dict:
        return messages.pop(0)

    async def send(message) -> None:
        raise AssertionError("middleware must not respond for a valid body")

    middleware = BodySizeLimitMiddleware(inner_app, max_body_bytes=65536)

    asyncio.run(middleware(_make_scope([]), receive, send))

    assert app_calls["n"] == 1
    assert b"".join(bodies) == b"a" * 40000 + b"b" * 20000


def test_non_http_scope_passes_through() -> None:
    lifespan_calls = {"n": 0}

    async def inner_app(scope, receive, send) -> None:
        lifespan_calls["n"] += 1

    async def receive() -> dict:
        raise AssertionError

    async def send(message) -> None:
        raise AssertionError

    middleware = BodySizeLimitMiddleware(inner_app, max_body_bytes=65536)

    asyncio.run(middleware({"type": "lifespan"}, receive, send))

    assert lifespan_calls["n"] == 1
