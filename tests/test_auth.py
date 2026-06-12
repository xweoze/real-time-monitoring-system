import tempfile
import unittest
import sqlite3
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
            "user_01",
            "password123",
            "서울 사용자",
            "KR-11",
            birth_date="1950-05-20",
            gender="FEMALE",
        )
        session = self.repository.login("user_01", "password123")

        self.assertEqual(user["role"], "USER")
        self.assertEqual(user["birthDate"], "1950-05-20")
        self.assertEqual(user["gender"], "FEMALE")
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

    def test_existing_database_is_migrated(self):
        database = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    region_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

        repository = AuthRepository(database)
        user = repository.create_user(
            "legacy_user",
            "password123",
            "기존 DB 사용자",
            "KR-11",
            birth_date="2018-01-02",
            gender="MALE",
        )

        self.assertEqual(user["birthDate"], "2018-01-02")
        self.assertEqual(repository.login("legacy_user", "password123")["user"]["gender"], "MALE")

    def test_rejects_invalid_profile_values(self):
        with self.assertRaises(ValueError):
            self.repository.create_user(
                "future_user",
                "password123",
                "미래 사용자",
                "KR-11",
                birth_date="2999-01-01",
            )
        with self.assertRaises(ValueError):
            self.repository.create_user(
                "gender_user",
                "password123",
                "성별 사용자",
                "KR-11",
                gender="INVALID",
            )


if __name__ == "__main__":
    unittest.main()
