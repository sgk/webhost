from __future__ import annotations

import unittest

from app.password_auth import (
    PASSWORD_MIN_LENGTH,
    generate_password,
    hash_password,
    password_document_id,
    validate_new_password,
    verify_password,
)


class PasswordAuthTest(unittest.TestCase):
    def test_hash_and_verify_password(self) -> None:
        encoded = hash_password("correct horse battery staple", salt=b"0123456789abcdef")

        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("incorrect password", encoded))

    def test_hash_uses_random_salt(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")

        self.assertNotEqual(first, second)

    def test_generated_password_is_valid_and_random(self) -> None:
        first = generate_password()
        second = generate_password()

        validate_new_password(first)
        validate_new_password(second)
        self.assertNotEqual(first, second)

    def test_malformed_hash_is_rejected(self) -> None:
        self.assertFalse(verify_password("correct horse battery staple", "invalid"))
        self.assertFalse(
            verify_password(
                "correct horse battery staple",
                "scrypt_v1$16384$8$1$not-valid-base64!$not-valid-base64!",
            )
        )
        self.assertFalse(
            verify_password(
                "correct horse battery staple",
                "scrypt_v1$32768$8$1$MDEyMzQ1Njc4OWFiY2RlZg$"
                "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            )
        )

    def test_short_password_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, str(PASSWORD_MIN_LENGTH)):
            validate_new_password("short")

    def test_document_id_normalizes_email(self) -> None:
        self.assertEqual(
            password_document_id(" Admin@Example.COM "),
            password_document_id("admin@example.com"),
        )


if __name__ == "__main__":
    unittest.main()
