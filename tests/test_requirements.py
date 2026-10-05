import unittest
from datetime import datetime
from eventforge.security import JwtCodec, PasswordHasher
from eventforge.invitations.state import InvitationStatus

class RequirementTests(unittest.TestCase):
    def test_password_and_token(self):
        hasher=PasswordHasher(iterations=1000); encoded=hasher.hash("correct-password")
        self.assertTrue(hasher.verify("correct-password",encoded)); self.assertFalse(hasher.verify("wrong",encoded))
        codec=JwtCodec("secret",ttl_seconds=60); self.assertEqual(codec.validate(codec.issue("7")).subject,"7")
        with self.assertRaises(Exception): codec.validate("malformed")
    def test_invalid_invitation_status(self):
        self.assertNotIn("WRONG", {x.value for x in InvitationStatus})
    def test_malformed_validation_input(self):
        with self.assertRaises(Exception): JwtCodec("", ttl_seconds=60)

if __name__ == "__main__": unittest.main()
