import tempfile
import unittest
from pathlib import Path

from auth import AuthRepository, AuthenticationError


class AuthRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = AuthRepository(Path(self.temp_dir.name) / "auth.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_signup_login_and_logout(self):
        user = self.repository.create_user(
            "user_01", "password123", "서울 사용자", "KR-11"
        )
        session = self.repository.login("user_01", "password123")

        self.assertEqual(user["role"], "USER")
        self.assertEqual(
            self.repository.authenticate(session["token"])["id"], user["id"]
        )

        self.repository.logout(session["token"])
        with self.assertRaises(AuthenticationError):
            self.repository.authenticate(session["token"])

    def test_default_national_admin_and_regional_operator(self):
        admin = self.repository.login("national_admin", "admin1234")
        operator = self.repository.create_user(
            "seoul_admin",
            "regional123",
            "서울 관제 관리자",
            "KR-11",
            role="REGIONAL_OPERATOR",
        )

        self.assertEqual(admin["user"]["role"], "NATIONAL_ADMIN")
        self.assertEqual(operator["regionId"], "KR-11")
        self.assertEqual(len(self.repository.list_operators()), 1)

    def test_rejects_duplicate_username(self):
        self.repository.create_user(
            "user_02", "password123", "첫 사용자", "KR-26"
        )
        with self.assertRaises(ValueError):
            self.repository.create_user(
                "user_02", "password456", "둘째 사용자", "KR-27"
            )


if __name__ == "__main__":
    unittest.main()
