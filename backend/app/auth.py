"""Small persistent session auth and dataset permissions."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core import ApiError, Settings
from app.db import Database


@dataclass(frozen=True)
class Principal:
    id: str
    email: str
    role: str


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310000)
    return salt.hex() + ':' + digest.hex()


def _matches(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split(':', 1)
        return hmac.compare_digest(_hash_password(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


class AuthService:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        if settings.auth_enabled:
            if not settings.admin_email or not settings.admin_password:
                raise ValueError('ADMIN_EMAIL and ADMIN_PASSWORD are required when auth is enabled')
            self.create_user(settings.admin_email, settings.admin_password, 'admin', if_missing=True)

    def create_user(self, email: str, password: str, role: str = 'user', if_missing: bool = False) -> str:
        email = email.strip().lower()
        if '@' not in email or len(password) < 12 or role not in ('admin', 'user'):
            raise ApiError(422, 'invalid_user', 'Email, role, or password is invalid')
        with self.db.connection() as con:
            row = con.execute('SELECT id FROM users WHERE email=?', [email]).fetchone()
            if row:
                if if_missing:
                    return row[0]
                raise ApiError(409, 'user_exists', 'User already exists')
            user_id = uuid4().hex
            con.execute('INSERT INTO users VALUES (?,?,?,?,?)', [user_id, email, role, _hash_password(password), datetime.now(timezone.utc)])
            return user_id

    def login(self, email: str, password: str) -> str:
        if not self.settings.auth_enabled:
            raise ApiError(404, 'not_found', 'Authentication is disabled')
        with self.db.connection() as con:
            row = con.execute('SELECT id,password_hash FROM users WHERE email=?', [email.strip().lower()]).fetchone()
            if not row or not _matches(password, row[1]):
                raise ApiError(401, 'invalid_credentials', 'Invalid email or password')
            token = secrets.token_urlsafe(32)
            con.execute('INSERT INTO sessions VALUES (?,?,?)', [hashlib.sha256(token.encode()).hexdigest(), row[0], datetime.now(timezone.utc) + timedelta(hours=12)])
            return token

    def current(self, authorization: str | None) -> Principal:
        if not self.settings.auth_enabled:
            return Principal('local', 'local', 'admin')
        if not authorization or not authorization.startswith('Bearer '):
            raise ApiError(401, 'authentication_required', 'Sign in to continue')
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        with self.db.connection() as con:
            row = con.execute('''SELECT users.id,users.email,users.role FROM sessions JOIN users ON sessions.user_id=users.id
                WHERE sessions.token_hash=? AND sessions.expires_at>?''', [digest, datetime.now(timezone.utc)]).fetchone()
        if not row:
            raise ApiError(401, 'authentication_required', 'Sign in to continue')
        return Principal(*row)

    def logout(self, authorization: str | None):
        if authorization and authorization.startswith('Bearer '):
            with self.db.connection() as con:
                con.execute('DELETE FROM sessions WHERE token_hash=?', [hashlib.sha256(authorization[7:].encode()).hexdigest()])

    def require_admin(self, user: Principal):
        if user.role != 'admin':
            raise ApiError(403, 'forbidden', 'Admin access required')

    def can_access(self, user: Principal, dataset_id: str) -> bool:
        if user.role == 'admin':
            return True
        with self.db.connection() as con:
            return bool(con.execute('''SELECT 1 FROM datasets WHERE id=? AND (owner_id=? OR EXISTS
                (SELECT 1 FROM dataset_permissions WHERE dataset_id=? AND user_id=?))''',
                [dataset_id, user.id, dataset_id, user.id]).fetchone())

    def require_dataset(self, user: Principal, dataset_id: str):
        if not self.can_access(user, dataset_id):
            raise ApiError(404, 'not_found', 'Dataset not found')

    def grant(self, dataset_id: str, user_id: str):
        with self.db.connection() as con:
            if not con.execute('SELECT 1 FROM datasets WHERE id=?', [dataset_id]).fetchone() or not con.execute('SELECT 1 FROM users WHERE id=?', [user_id]).fetchone():
                raise ApiError(404, 'not_found', 'Dataset or user not found')
            con.execute('INSERT OR IGNORE INTO dataset_permissions VALUES (?,?)', [dataset_id, user_id])
