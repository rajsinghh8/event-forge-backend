import unittest

from eventforge.errors import AuthenticationError
from eventforge.security import JwtCodec, PasswordHasher


class PasswordHasherTests(unittest.TestCase):
    def test_hash_verifies_and_is_salted(self) -> None:
        hasher = PasswordHasher(iterations=1_000)
        first = hasher.hash("correct horse battery staple")
        second = hasher.hash("correct horse battery staple")

        self.assertTrue(hasher.verify("correct horse battery staple", first))
        self.assertFalse(hasher.verify("wrong password", first))
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("pbkdf2_sha256$1000$"))


class JwtCodecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = JwtCodec("a-long-test-secret", "eventforge-test", 60)

    def test_valid_token(self) -> None:
        token = self.codec.issue("user-123", now=1_000)
        claims = self.codec.validate(token, now=1_001)
        self.assertEqual("user-123", claims.subject)
        self.assertEqual(1_060, claims.expires_at)

    def test_tampered_token_is_rejected(self) -> None:
        token = self.codec.issue("user-123", now=1_000)
        header, payload, signature = token.split(".")
        replacement = "A" if signature[-1] != "A" else "B"
        with self.assertRaises(AuthenticationError):
            self.codec.validate(f"{header}.{payload}.{signature[:-1]}{replacement}", now=1_001)

    def test_malformed_token_is_rejected(self) -> None:
        for token in ("not-a-jwt", "a.b.c", "...", "eyJhbGciOiJIUzI1NiJ9.bad.XXX"):
            with self.subTest(token=token), self.assertRaises(AuthenticationError):
                self.codec.validate(token, now=1_001)

    def test_expired_token_is_rejected(self) -> None:
        token = self.codec.issue("user-123", now=1_000)
        with self.assertRaisesRegex(AuthenticationError, "expired"):
            self.codec.validate(token, now=1_060)


if __name__ == "__main__":
    unittest.main()
