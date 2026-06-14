"""SQLite-backed accounts and bearer-token sessions."""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from regions import REGION_BY_ID


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class AuthRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    region_id TEXT,
                    birth_date TEXT,
                    gender TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "birth_date" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN birth_date TEXT")
            if "gender" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN gender TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS guardian_links (
                    guardian_id TEXT NOT NULL,
                    protected_user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (guardian_id, protected_user_id),
                    FOREIGN KEY(guardian_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(protected_user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
        self._ensure_default_admin()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
        ).hex()

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "role": row["role"],
            "regionId": row["region_id"],
            "birthDate": row["birth_date"],
            "gender": row["gender"] or "UNDISCLOSED",
            "createdAt": row["created_at"],
        }

    def _insert_user(
        self,
        username: str,
        password: str,
        display_name: str,
        role: str,
        region_id: Optional[str],
        birth_date: Optional[str] = None,
        gender: str = "UNDISCLOSED",
    ) -> dict:
        salt = os.urandom(16).hex()
        user_id = "U-" + uuid.uuid4().hex[:10]
        created_at = self._now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        id, username, password_hash, salt, display_name, role,
                        region_id, birth_date, gender, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        self._hash_password(password, salt),
                        salt,
                        display_name,
                        role,
                        region_id,
                        birth_date,
                        gender,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("이미 사용 중인 아이디입니다.") from exc
        return {
            "id": user_id,
            "username": username,
            "displayName": display_name,
            "role": role,
            "regionId": region_id,
            "birthDate": birth_date,
            "gender": gender,
            "createdAt": created_at,
        }

    def _ensure_default_admin(self) -> None:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM users WHERE username = ?", ("national_admin",)
            ).fetchone()
        if not exists:
            self._insert_user(
                "national_admin",
                "admin1234",
                "전국 관제 관리자",
                "NATIONAL_ADMIN",
                None,
            )

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str,
        region_id: str,
        role: str = "USER",
        birth_date: Optional[str] = None,
        gender: str = "UNDISCLOSED",
    ) -> dict:
        username = str(username or "").strip()
        password = str(password or "")
        display_name = str(display_name or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{4,30}", username):
            raise ValueError("아이디는 영문, 숫자, _, -, . 조합 4~30자로 입력해 주세요.")
        if len(password) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        if not display_name or len(display_name) > 30:
            raise ValueError("표시 이름은 1~30자로 입력해 주세요.")
        if role not in {"USER", "GUARDIAN", "REGIONAL_OPERATOR"}:
            raise ValueError("지원하지 않는 계정 역할입니다.")
        if role != "GUARDIAN" and region_id not in REGION_BY_ID:
            raise ValueError("유효한 지역을 선택해 주세요.")
        if role == "GUARDIAN":
            region_id = None
        gender = str(gender or "UNDISCLOSED").upper()
        if gender not in {"FEMALE", "MALE", "OTHER", "UNDISCLOSED"}:
            raise ValueError("유효한 성별 값을 선택해 주세요.")
        birth_date = str(birth_date or "").strip() or None
        if birth_date:
            try:
                parsed_birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("생년월일 형식이 올바르지 않습니다.") from exc
            today = datetime.now(timezone.utc).date()
            if parsed_birth_date > today:
                raise ValueError("생년월일은 미래 날짜일 수 없습니다.")
            if parsed_birth_date.year < today.year - 130:
                raise ValueError("생년월일을 다시 확인해 주세요.")
        return self._insert_user(
            username,
            password,
            display_name,
            role,
            region_id,
            birth_date,
            gender,
        )

    def login(self, username: str, password: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (str(username or "").strip(),),
            ).fetchone()
            if not row:
                raise AuthenticationError("아이디 또는 비밀번호가 올바르지 않습니다.")
            actual = self._hash_password(str(password or ""), row["salt"])
            if not hmac.compare_digest(actual, row["password_hash"]):
                raise AuthenticationError("아이디 또는 비밀번호가 올바르지 않습니다.")

            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            created_at = datetime.now(timezone.utc)
            expires_at = created_at + timedelta(hours=12)
            connection.execute(
                """
                INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    token_hash,
                    row["id"],
                    created_at.isoformat(timespec="seconds"),
                    expires_at.isoformat(timespec="seconds"),
                ),
            )
        return {
            "token": token,
            "expiresAt": expires_at.isoformat(timespec="seconds"),
            "user": self._public_user(row),
        }

    def authenticate(self, token: str) -> dict:
        if not token:
            raise AuthenticationError("로그인이 필요합니다.")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (self._now(),)
            )
            row = connection.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if not row:
            raise AuthenticationError("로그인 세션이 만료되었거나 유효하지 않습니다.")
        return self._public_user(row)

    def logout(self, token: str) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
            )

    def list_operators(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM users
                WHERE role = 'REGIONAL_OPERATOR'
                ORDER BY region_id, display_name
                """
            ).fetchall()
        return [self._public_user(row) for row in rows]

    def get_user(self, user_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._public_user(row) if row else None

    def list_members(self, region_id: Optional[str] = None) -> list[dict]:
        parameters = []
        where = "WHERE role = 'USER'"
        if region_id:
            if region_id not in REGION_BY_ID:
                raise ValueError("유효한 지역을 선택해 주세요.")
            where += " AND region_id = ?"
            parameters.append(region_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM users
                {where}
                ORDER BY created_at DESC, display_name
                """,
                parameters,
            ).fetchall()
        return [self._public_user(row) for row in rows]

    def member_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM users WHERE role = 'USER'"
            ).fetchall()
        return {row["id"] for row in rows}

    def link_guardian(self, protected_user_id: str, guardian_username: str) -> dict:
        guardian_username = str(guardian_username or "").strip()
        if not guardian_username:
            raise ValueError("보호자 아이디를 입력해 주세요.")
        with self._connect() as connection:
            protected = connection.execute(
                "SELECT * FROM users WHERE id = ? AND role = 'USER'",
                (protected_user_id,),
            ).fetchone()
            if not protected:
                raise KeyError("보호 대상 사용자를 찾을 수 없습니다.")
            guardian = connection.execute(
                "SELECT * FROM users WHERE username = ? AND role = 'GUARDIAN'",
                (guardian_username,),
            ).fetchone()
            if not guardian:
                raise KeyError("해당 아이디의 보호자 계정을 찾을 수 없습니다.")
            try:
                connection.execute(
                    """
                    INSERT INTO guardian_links (
                        guardian_id, protected_user_id, created_at
                    ) VALUES (?, ?, ?)
                    """,
                    (guardian["id"], protected_user_id, self._now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("이미 연결된 보호자입니다.") from exc
        return self._public_user(guardian)

    def guardians_for_user(self, protected_user_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT users.*
                FROM guardian_links
                JOIN users ON users.id = guardian_links.guardian_id
                WHERE guardian_links.protected_user_id = ?
                ORDER BY guardian_links.created_at, users.display_name
                """,
                (protected_user_id,),
            ).fetchall()
        return [self._public_user(row) for row in rows]

    def wards_for_guardian(self, guardian_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT users.*
                FROM guardian_links
                JOIN users ON users.id = guardian_links.protected_user_id
                WHERE guardian_links.guardian_id = ?
                ORDER BY users.display_name
                """,
                (guardian_id,),
            ).fetchall()
        return [self._public_user(row) for row in rows]

    def unlink_guardian(self, protected_user_id: str, guardian_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM guardian_links
                WHERE protected_user_id = ? AND guardian_id = ?
                """,
                (protected_user_id, guardian_id),
            )
        if cursor.rowcount == 0:
            raise KeyError("연결된 보호자를 찾을 수 없습니다.")

    def update_member(
        self,
        user_id: str,
        display_name: str,
        region_id: str,
        birth_date: Optional[str] = None,
        gender: str = "UNDISCLOSED",
    ) -> dict:
        display_name = str(display_name or "").strip()
        if not display_name or len(display_name) > 30:
            raise ValueError("표시 이름은 1~30자로 입력해 주세요.")
        if region_id not in REGION_BY_ID:
            raise ValueError("유효한 지역을 선택해 주세요.")
        gender = str(gender or "UNDISCLOSED").upper()
        if gender not in {"FEMALE", "MALE", "OTHER", "UNDISCLOSED"}:
            raise ValueError("유효한 성별 값을 선택해 주세요.")
        birth_date = str(birth_date or "").strip() or None
        if birth_date:
            try:
                parsed_birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("생년월일 형식이 올바르지 않습니다.") from exc
            today = datetime.now(timezone.utc).date()
            if parsed_birth_date > today:
                raise ValueError("생년월일은 미래 날짜일 수 없습니다.")
            if parsed_birth_date.year < today.year - 130:
                raise ValueError("생년월일을 다시 확인해 주세요.")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ? AND role = 'USER'", (user_id,)
            ).fetchone()
            if not row:
                raise KeyError("회원을 찾을 수 없습니다.")
            connection.execute(
                """
                UPDATE users
                SET display_name = ?, region_id = ?, birth_date = ?, gender = ?
                WHERE id = ?
                """,
                (display_name, region_id, birth_date, gender, user_id),
            )
            updated = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._public_user(updated)

    def delete_member(self, user_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ? AND role = 'USER'", (user_id,)
            ).fetchone()
            if not row:
                raise KeyError("회원을 찾을 수 없습니다.")
            member = self._public_user(row)
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return member
