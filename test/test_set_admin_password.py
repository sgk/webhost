from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from tools import set_admin_password


class FakeSnapshot:
    exists = False


class FakeDocument:
    def __init__(self):
        self.data: dict | None = None

    def get(self) -> FakeSnapshot:
        return FakeSnapshot()

    def set(self, data: dict) -> None:
        self.data = dict(data)


class FakeCollection:
    def __init__(self, document: FakeDocument):
        self._document = document

    def document(self, _document_id: str) -> FakeDocument:
        return self._document


class SetAdminPasswordTest(unittest.TestCase):
    def run_cli(self, arguments: list[str], generated_password: str) -> tuple[int, str, FakeDocument]:
        document = FakeDocument()
        output = StringIO()
        with (
            patch.object(set_admin_password, "get_client", return_value=object()),
            patch.object(set_admin_password, "list_admin_sites", return_value=[object()]),
            patch.object(
                set_admin_password,
                "get_collection",
                return_value=FakeCollection(document),
            ),
            patch.object(
                set_admin_password,
                "generate_password",
                return_value=generated_password,
            ),
            patch("builtins.input", return_value="y"),
            patch("sys.argv", ["set_admin_password.py", *arguments]),
            redirect_stdout(output),
        ):
            result = set_admin_password.main()
        return result, output.getvalue(), document

    def test_generates_and_displays_password_when_omitted(self) -> None:
        generated = "generated-password-123456"

        result, output, document = self.run_cli(["admin@example.com"], generated)

        self.assertEqual(result, 0)
        self.assertIn(f"発行パスワード: {generated}", output)
        self.assertIsNotNone(document.data)
        self.assertNotIn(generated, str(document.data))

    def test_uses_specified_password_without_displaying_it(self) -> None:
        specified = "specified-password-123456"

        result, output, document = self.run_cli(
            ["admin@example.com", "--password", specified],
            "unused-generated-password",
        )

        self.assertEqual(result, 0)
        self.assertNotIn("発行パスワード:", output)
        self.assertIsNotNone(document.data)
        self.assertNotIn(specified, str(document.data))


if __name__ == "__main__":
    unittest.main()
