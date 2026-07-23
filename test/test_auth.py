from __future__ import annotations

from dataclasses import dataclass, field
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from starlette.requests import Request

from app import auth
from app.password_auth import hash_password, password_document_id


class FakeSnapshot:
    def __init__(self, data: dict | None = None):
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict:
        return dict(self._data or {})


@dataclass
class FakeDocument:
    snapshot: FakeSnapshot
    writes: list[dict] = field(default_factory=list)

    def get(self) -> FakeSnapshot:
        return self.snapshot

    def set(self, data: dict) -> None:
        self.writes.append(dict(data))


class FakeCollection:
    def __init__(self, documents: dict[str, FakeDocument]):
        self.documents = documents

    def document(self, document_id: str) -> FakeDocument:
        return self.documents[document_id]


def make_form_request(data: dict[str, str], *, csrf_cookie: str = "") -> Request:
    body = urlencode(data).encode("utf-8")
    headers = [
        (b"content-type", b"application/x-www-form-urlencoded"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if csrf_cookie:
        headers.append((b"cookie", f"{auth.ADMIN_PASSWORD_CSRF_COOKIE}={csrf_cookie}".encode("ascii")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/auth/password",
        "raw_path": b"/auth/password",
        "query_string": b"",
        "headers": headers,
        "client": ("192.0.2.1", 12345),
        "server": ("example.test", 443),
    }
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class PasswordLoginTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        auth._password_login_attempts.clear()
        auth._session_cache.clear()

    async def test_valid_password_creates_admin_session(self) -> None:
        email = "admin@example.com"
        csrf_token = "csrf-token"
        credential_document = FakeDocument(
            FakeSnapshot(
                {
                    "email": email,
                    "password_hash": hash_password(
                        "correct horse battery staple",
                        salt=b"0123456789abcdef",
                    ),
                    "enabled": True,
                }
            )
        )
        session_document = FakeDocument(FakeSnapshot())
        collections = {
            "admin_passwords": FakeCollection(
                {password_document_id(email): credential_document}
            ),
            "admin_sessions": FakeCollection({"session-token": session_document}),
        }

        def fake_get_collection(_db, name: str):
            if name == "admin_sessions":
                return SessionCollection(session_document)
            return collections[name]

        request = make_form_request(
            {
                "email": " Admin@Example.COM ",
                "password": "correct horse battery staple",
                "next": "/sites/site-a",
                "csrf_token": csrf_token,
            },
            csrf_cookie=csrf_token,
        )

        with (
            patch.object(auth, "get_client", return_value=object()),
            patch.object(auth, "get_collection", side_effect=fake_get_collection),
            patch.object(auth, "list_admin_sites", return_value=[object()]),
            patch.object(auth.secrets, "token_urlsafe", return_value="session-token"),
        ):
            response = await auth.auth_password(request)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/sites/site-a")
        self.assertEqual(len(session_document.writes), 1)
        self.assertEqual(session_document.writes[0]["email"], email)
        self.assertEqual(session_document.writes[0]["auth_method"], "password")
        self.assertIn(auth.ADMIN_SESSION_COOKIE, response.headers["set-cookie"])

    async def test_invalid_csrf_does_not_access_firestore(self) -> None:
        request = make_form_request(
            {
                "email": "admin@example.com",
                "password": "correct horse battery staple",
                "next": "/sites",
                "csrf_token": "form-token",
            },
            csrf_cookie="cookie-token",
        )

        with patch.object(auth, "get_client") as get_client:
            response = await auth.auth_password(request)

        self.assertEqual(response.status_code, 200)
        get_client.assert_not_called()


class SessionCollection:
    def __init__(self, document: FakeDocument):
        self._document = document

    def document(self, _document_id: str) -> FakeDocument:
        return self._document


if __name__ == "__main__":
    unittest.main()
