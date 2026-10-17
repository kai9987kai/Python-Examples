"""Bank Manager backend: offline educational ledger, SQLite, no third-party deps.

Balances are stored as integer pence, and all money mutations are atomic.
This is NOT suitable as the ledger for a regulated financial institution.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

DB_FILE = Path(__file__).with_name("bankmanaging.db")
MAX_PENCE = 100_000_000_000  # £1 billion: per-account and per-operation limit
# OWASP scrypt alternative when Argon2id is unavailable (memory-hard): N=2**17,r=8,p=1
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 17, 8, 1
USERNAME_RE = re.compile(r"^[A-Za-z0-9_. -]{3,50}$")
MONEY_RE = re.compile(r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{5,23}$")


class BankError(Exception):
    """Expected user-facing validation or business error."""


class AccessDenied(BankError):
    pass


@dataclass(frozen=True)
class Session:
    user_id: int
    username: str
    role: str
    must_change_password: bool = False
    session_version: int = 0


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_money(raw: str) -> int:
    if not isinstance(raw, str) or not MONEY_RE.fullmatch(raw.strip()):
        raise BankError("Enter a non-negative amount with up to two decimal places (e.g. 12.50).")
    value = Decimal(raw.strip()) * 100
    pence = int(value)
    if pence > MAX_PENCE:
        raise BankError("Amount exceeds the permitted demonstration limit.")
    return pence


def positive_money(raw: str) -> int:
    pence = parse_money(raw)
    if pence == 0:
        raise BankError("Amount must be greater than zero.")
    return pence


def pounds(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    p = abs(int(pence))
    return f"{sign}£{p // 100:,}.{p % 100:02d}"


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, maxmem=256 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _password_ok(password: str, encoded: str) -> bool:
    try:
        method, n, r, p, salt, expected = encoded.split("$")
        if method != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        # Never accept unbounded cost parameters read from a potentially modified DB.
        if n != SCRYPT_N or r != SCRYPT_R or p != SCRYPT_P:
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=n, r=r, p=p, maxmem=256 * 1024 * 1024)
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _check_password_strength(password: str) -> None:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        raise BankError("Use a password of 12–256 characters (a long passphrase is ideal).")
    if not password.strip():
        raise BankError("Password cannot be blank.")


def _clean_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise BankError(f"{field} must be text.")
    text = value.strip()
    if not text or len(text) > limit:
        raise BankError(f"{field} must contain 1–{limit} characters.")
    return text


def _valid_username(username: str) -> str:
    name = _clean_text(username, "Username", 50)
    if not USERNAME_RE.fullmatch(name):
        raise BankError("Username: 3–50 letters, digits, spaces, periods, underscores or hyphens.")
    return name


def _valid_age(age: Any) -> int:
    if isinstance(age, bool) or not str(age).strip().isdigit():
        raise BankError("Age must be a whole number.")
    value = int(age)
    if not 0 <= value <= 120:
        raise BankError("Age must be between 0 and 120.")
    return value


def _valid_phone(phone: str) -> str:
    value = _clean_text(phone, "Telephone number", 24)
    if not PHONE_RE.fullmatch(value):
        raise BankError("Enter a valid-looking phone number (stored as text to preserve leading zeros).")
    return value


def _csv_safe(value: Any) -> Any:
    """Mitigate CSV formula injection when opened in spreadsheet applications."""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


class BankDB:
    def __init__(self, path: str | Path = DB_FILE):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.migration_backup: Path | None = None
        try:
            legacy = self._has_legacy()
            if legacy:
                self.migration_backup = self._backup_legacy()
            self._create_schema()
            if legacy:
                self._migrate_legacy()
        except Exception:
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    def _table_exists(self, name: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _has_legacy(self) -> bool:
        return any(self._table_exists(t) for t in ("bank", "staff", "admin"))

    def _backup_legacy(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.path.with_name(f"{self.path.stem}.legacy-backup-{timestamp}-{secrets.token_hex(3)}.db")
        with sqlite3.connect(target) as copy:
            self.conn.backup(copy)
        return target

    def _create_schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','employee')),
            salary_pence INTEGER NOT NULL DEFAULT 0 CHECK(salary_pence >= 0),
            position TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            must_change INTEGER NOT NULL DEFAULT 0 CHECK(must_change IN (0,1)),
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            session_version INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
            account_no INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            address TEXT NOT NULL,
            balance_pence INTEGER NOT NULL CHECK(balance_pence BETWEEN 0 AND 100000000000),
            account_type TEXT NOT NULL,
            phone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','CLOSED')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_no INTEGER NOT NULL REFERENCES accounts(account_no),
            kind TEXT NOT NULL CHECK(kind IN ('OPENING','DEPOSIT','WITHDRAWAL','TRANSFER_IN','TRANSFER_OUT')),
            amount_pence INTEGER NOT NULL CHECK(amount_pence >= 0),
            balance_after_pence INTEGER NOT NULL CHECK(balance_after_pence >= 0),
            counterparty INTEGER REFERENCES accounts(account_no),
            transfer_ref TEXT,
            actor_id INTEGER REFERENCES users(id),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_no, id DESC);
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id),
            event TEXT NOT NULL,
            target TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_id ON audit_log(id DESC);
        """)
        self.conn.execute("PRAGMA user_version=2")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _audit(self, db: sqlite3.Connection, actor: int | None, event: str,
               target: str, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO audit_log(actor_id,event,target,details,created_at) VALUES(?,?,?,?,?)",
                   (actor, event, target, json.dumps(details or {}, ensure_ascii=False), utcnow()))

    def _migrate_legacy(self) -> None:
        """One-time import, then remove plaintext legacy tables; original lives in backup.

        Old integer balances are treated as pounds, not pence.
        """
        try:
            with self._tx() as db:
                names = {r[0].casefold() for r in db.execute("SELECT username FROM users")}
                if self._table_exists("admin"):
                    for row in db.execute('SELECT name, "pass" FROM admin').fetchall():
                        username, password = str(row[0] or "").strip(), str(row[1] or "")
                        if not username or not password or username.casefold() in names:
                            continue
                        db.execute("INSERT INTO users(username,password_hash,role,must_change,created_at) VALUES(?,?, 'admin',1,?)",
                                   (username, _password_hash(password), utcnow()))
                        names.add(username.casefold())
                if self._table_exists("staff"):
                    for idx, row in enumerate(db.execute('SELECT name, "pass", salary, position FROM staff').fetchall(), 1):
                        base = str(row[0] or "").strip() or f"legacy_staff_{idx}"
                        candidate = base
                        n = 1
                        while candidate.casefold() in names:
                            candidate = f"{base[:35]}_staff_{n}"
                            n += 1
                        names.add(candidate.casefold())
                        password = str(row[1] or "") or secrets.token_urlsafe(48)
                        salary = int(Decimal(str(row[2] or 0)) * 100)
                        if salary < 0:
                            raise BankError("Legacy staff contains a negative salary. Correct it in the backup before retrying.")
                        db.execute("INSERT INTO users(username,password_hash,role,salary_pence,position,must_change,created_at) "
                                   "VALUES(?,?,'employee',?,?,1,?)",
                                   (candidate, _password_hash(password), salary, str(row[3] or ""), utcnow()))
                if self._table_exists("bank"):
                    for row in db.execute("SELECT acc_no,name,age,address,balance,account_type,mobile_number FROM bank").fetchall():
                        try:
                            acct = int(row[0])
                            balance_decimal = Decimal(str(row[4] or 0)) * 100
                            if not balance_decimal.is_finite() or balance_decimal != balance_decimal.to_integral_value():
                                raise ValueError("unrepresentable legacy balance")
                            amount = int(balance_decimal)
                            if amount < 0 or amount > MAX_PENCE or acct < 1:
                                raise ValueError("negative/excessive balance or invalid account number")
                            db.execute("INSERT INTO accounts(account_no,full_name,age,address,balance_pence,account_type,phone,created_at) "
                                       "VALUES(?,?,?,?,?,?,?,?)",
                                       (acct, str(row[1] or ""), int(row[2] or 0), str(row[3] or ""), amount,
                                        str(row[5] or ""), str(row[6] or ""), utcnow()))
                            db.execute("INSERT INTO transactions(account_no,kind,amount_pence,balance_after_pence,note,created_at) "
                                       "VALUES(?,'OPENING',?,?,?,?)",
                                       (acct, amount, amount, "Imported legacy opening balance", utcnow()))
                        except (ValueError, InvalidOperation, sqlite3.IntegrityError) as exc:
                            raise BankError(f"Legacy account {row[0]!r} could not be migrated safely: {exc}") from exc
                for table in ("bank", "staff", "admin"):
                    if self._table_exists(table):
                        db.execute(f'DROP TABLE "{table}"')  # trusted fixed names only
                self._audit(db, None, "LEGACY_MIGRATION", "database",
                            {"backup": self.migration_backup.name if self.migration_backup else ""})
        except Exception as exc:
            raise BankError(f"Legacy migration failed; source backup retained at {self.migration_backup}: {exc}") from exc

    def needs_admin_setup(self) -> bool:
        return self.conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone() is None

    def create_initial_admin(self, username: str, password: str) -> None:
        username = _valid_username(username)
        _check_password_strength(password)
        with self._tx() as db:
            if db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                raise AccessDenied("Administrator has already been configured.")
            db.execute("INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,'admin',?)",
                       (username, _password_hash(password), utcnow()))
            self._audit(db, None, "FIRST_ADMIN_CREATED", username)

    def authenticate(self, username: str, password: str) -> Session:
        with self._tx() as db:
            user = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)).fetchone()
            if not user or not user["active"]:
                raise AccessDenied("Invalid username or password.")
            if user["locked_until"] and user["locked_until"] > utcnow():
                raise AccessDenied("Account temporarily locked. Try again in 15 minutes.")
            if not _password_ok(password, user["password_hash"]):
                failures = user["failed_attempts"] + 1
                lock = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds") if failures >= 5 else None
                db.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                           (0 if lock else failures, lock, user["id"]))
                raise_pending = "Invalid username or password." if not lock else "Account temporarily locked. Try again in 15 minutes."
            else:
                db.execute("UPDATE users SET failed_attempts=0,locked_until=NULL WHERE id=?", (user["id"],))
                self._audit(db, user["id"], "LOGIN", user["username"])
                return Session(user["id"], user["username"], user["role"], bool(user["must_change"]), user["session_version"])
        # Must throw *after* COMMIT so failed attempt counters persist.
        raise AccessDenied(raise_pending)

    def _require(self, session: Session, role: str | None = None, allow_password_change: bool = False) -> sqlite3.Row:
        if not isinstance(session, Session):
            raise AccessDenied("Sign in to continue.")
        user = self.conn.execute("SELECT * FROM users WHERE id=?", (session.user_id,)).fetchone()
        if not user or not user["active"] or user["username"] != session.username or user["role"] != session.role or user["session_version"] != session.session_version:
            raise AccessDenied("Your session is no longer valid; sign in again.")
        if role and user["role"] != role:
            raise AccessDenied("Administrator permission required.")
        if user["must_change"] and not allow_password_change:
            raise AccessDenied("Change your temporary password before continuing.")
        return user

    def change_own_password(self, session: Session, old: str, new: str) -> Session:
        user = self._require(session, allow_password_change=True)
        _check_password_strength(new)
        if not _password_ok(old, user["password_hash"]):
            raise AccessDenied("Current password is incorrect.")
        if hmac.compare_digest(old, new):
            raise BankError("New password must differ from current password.")
        hashed = _password_hash(new)
        with self._tx() as db:
            db.execute("UPDATE users SET password_hash=?,must_change=0,failed_attempts=0,locked_until=NULL,session_version=session_version+1 WHERE id=?",
                       (hashed, user["id"]))
            self._audit(db, user["id"], "PASSWORD_CHANGED", user["username"])
        return Session(user["id"], user["username"], user["role"], False, user["session_version"] + 1)

    def create_employee(self, actor: Session, username: str, password: str,
                        salary: str, position: str) -> int:
        self._require(actor, "admin")
        username, salary_pence = _valid_username(username), parse_money(salary)
        position = _clean_text(position, "Position", 80)
        _check_password_strength(password)
        with self._tx() as db:
            try:
                result = db.execute("INSERT INTO users(username,password_hash,role,salary_pence,position,must_change,created_at) "
                                    "VALUES(?,?,'employee',?,?,1,?)",
                                    (username, _password_hash(password), salary_pence, position, utcnow()))
            except sqlite3.IntegrityError as exc:
                raise BankError("That username already exists.") from exc
            self._audit(db, actor.user_id, "EMPLOYEE_CREATED", username)
            return int(result.lastrowid)

    def list_employees(self, actor: Session) -> list[dict[str, Any]]:
        self._require(actor, "admin")
        return [dict(r) for r in self.conn.execute(
            "SELECT id,username,salary_pence,position,active,must_change FROM users WHERE role='employee' ORDER BY username COLLATE NOCASE")]

    def update_employee(self, actor: Session, user_id: int, *, username: str,
                        salary: str, position: str, active: bool) -> None:
        self._require(actor, "admin")
        username, salary_pence = _valid_username(username), parse_money(salary)
        position = _clean_text(position, "Position", 80)
        with self._tx() as db:
            try:
                result = db.execute("UPDATE users SET username=?,salary_pence=?,position=?,active=?,session_version=session_version+1 "
                                    "WHERE id=? AND role='employee'",
                                    (username, salary_pence, position, int(bool(active)), user_id))
            except sqlite3.IntegrityError as exc:
                raise BankError("That username already exists.") from exc
            if not result.rowcount:
                raise BankError("Employee not found.")
            self._audit(db, actor.user_id, "EMPLOYEE_UPDATED", str(user_id), {"active": bool(active)})

    def reset_employee_password(self, actor: Session, user_id: int, password: str) -> None:
        self._require(actor, "admin")
        _check_password_strength(password)
        with self._tx() as db:
            result = db.execute("UPDATE users SET password_hash=?,must_change=1,failed_attempts=0,locked_until=NULL,session_version=session_version+1 "
                                "WHERE id=? AND role='employee'", (_password_hash(password), user_id))
            if not result.rowcount:
                raise BankError("Employee not found.")
            self._audit(db, actor.user_id, "EMPLOYEE_PASSWORD_RESET", str(user_id))

    def create_account(self, actor: Session, name: str, age: Any, address: str,
                       balance: str, account_type: str, phone: str) -> int:
        self._require(actor)
        name = _clean_text(name, "Name", 120)
        age = _valid_age(age)
        address = _clean_text(address, "Address", 300)
        account_type = _clean_text(account_type, "Account type", 50)
        phone = _valid_phone(phone)
        initial = parse_money(balance)
        with self._tx() as db:
            cursor = db.execute("INSERT INTO accounts(full_name,age,address,balance_pence,account_type,phone,created_at) "
                                "VALUES(?,?,?,?,?,?,?)", (name, age, address, initial, account_type, phone, utcnow()))
            account_no = int(cursor.lastrowid)
            self._record_tx(db, account_no, "OPENING", initial, initial, actor.user_id, "New account")
            self._audit(db, actor.user_id, "ACCOUNT_CREATED", str(account_no))
            return account_no

    def _account(self, db: sqlite3.Connection, account_no: int, active: bool = True) -> sqlite3.Row:
        try:
            number = int(account_no)
        except (ValueError, TypeError) as exc:
            raise BankError("Account number must be an integer.") from exc
        row = db.execute("SELECT * FROM accounts WHERE account_no=?", (number,)).fetchone()
        if row is None or (active and row["status"] != "ACTIVE"):
            raise BankError("Active account not found." if active else "Account not found.")
        return row

    def get_account(self, actor: Session, account_no: int) -> dict[str, Any]:
        self._require(actor)
        return dict(self._account(self.conn, account_no, active=False))

    def list_accounts(self, actor: Session, search: str = "", include_closed: bool = False) -> list[dict[str, Any]]:
        self._require(actor)
        term = f"%{search.strip()}%"
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM accounts WHERE (? OR status='ACTIVE') AND "
            "(CAST(account_no AS TEXT) LIKE ? OR full_name LIKE ? OR account_type LIKE ? OR phone LIKE ?) "
            "ORDER BY account_no DESC LIMIT 10000",
            (int(include_closed), term, term, term, term))]

    def update_account(self, actor: Session, account_no: int, *, name: str, age: Any,
                       address: str, account_type: str, phone: str) -> None:
        self._require(actor)
        name, age = _clean_text(name, "Name", 120), _valid_age(age)
        address = _clean_text(address, "Address", 300)
        account_type = _clean_text(account_type, "Account type", 50)
        phone = _valid_phone(phone)
        with self._tx() as db:
            self._account(db, account_no)
            db.execute("UPDATE accounts SET full_name=?,age=?,address=?,account_type=?,phone=? WHERE account_no=?",
                       (name, age, address, account_type, phone, account_no))
            self._audit(db, actor.user_id, "ACCOUNT_UPDATED", str(account_no))

    def close_account(self, actor: Session, account_no: int) -> None:
        self._require(actor)
        with self._tx() as db:
            account = self._account(db, account_no)
            if account["balance_pence"] != 0:
                raise BankError("Account must have a zero balance before closure.")
            db.execute("UPDATE accounts SET status='CLOSED' WHERE account_no=?", (account_no,))
            self._audit(db, actor.user_id, "ACCOUNT_CLOSED", str(account_no))

    def reopen_account(self, actor: Session, account_no: int) -> None:
        self._require(actor, "admin")
        with self._tx() as db:
            account = self._account(db, account_no, active=False)
            if account["status"] != "CLOSED":
                raise BankError("Account is already active.")
            db.execute("UPDATE accounts SET status='ACTIVE' WHERE account_no=?", (account_no,))
            self._audit(db, actor.user_id, "ACCOUNT_REOPENED", str(account_no))

    def _record_tx(self, db: sqlite3.Connection, account_no: int, kind: str, amount: int,
                   result: int, actor: int | None, note: str, counterparty: int | None = None,
                   transfer_ref: str | None = None) -> None:
        db.execute("INSERT INTO transactions(account_no,kind,amount_pence,balance_after_pence,actor_id,note,counterparty,transfer_ref,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?)",
                   (account_no, kind, amount, result, actor, note, counterparty, transfer_ref, utcnow()))

    def deposit(self, actor: Session, account_no: int, amount: str, note: str = "") -> int:
        self._require(actor)
        pence = positive_money(amount)
        note = note.strip()[:300]
        with self._tx() as db:
            account = self._account(db, account_no)
            new_balance = account["balance_pence"] + pence
            if new_balance > MAX_PENCE:
                raise BankError("Account balance would exceed the demonstration limit.")
            db.execute("UPDATE accounts SET balance_pence=? WHERE account_no=?", (new_balance, account_no))
            self._record_tx(db, account_no, "DEPOSIT", pence, new_balance, actor.user_id, note)
            self._audit(db, actor.user_id, "DEPOSIT", str(account_no), {"pence": pence})
            return new_balance

    def withdraw(self, actor: Session, account_no: int, amount: str, note: str = "") -> int:
        self._require(actor)
        pence = positive_money(amount)
        note = note.strip()[:300]
        with self._tx() as db:
            account = self._account(db, account_no)
            if account["balance_pence"] < pence:
                raise BankError("Insufficient balance.")
            new_balance = account["balance_pence"] - pence
            db.execute("UPDATE accounts SET balance_pence=? WHERE account_no=?", (new_balance, account_no))
            self._record_tx(db, account_no, "WITHDRAWAL", pence, new_balance, actor.user_id, note)
            self._audit(db, actor.user_id, "WITHDRAWAL", str(account_no), {"pence": pence})
            return new_balance

    def transfer(self, actor: Session, source: int, destination: int, amount: str,
                 note: str = "") -> str:
        self._require(actor)
        pence = positive_money(amount)
        note = note.strip()[:300]
        if int(source) == int(destination):
            raise BankError("Source and destination must be different accounts.")
        with self._tx() as db:
            src = self._account(db, source)
            dst = self._account(db, destination)
            if src["balance_pence"] < pence:
                raise BankError("Insufficient balance.")
            if dst["balance_pence"] + pence > MAX_PENCE:
                raise BankError("Destination balance would exceed the demonstration limit.")
            src_new, dst_new = src["balance_pence"] - pence, dst["balance_pence"] + pence
            ref = uuid.uuid4().hex[:16].upper()
            db.execute("UPDATE accounts SET balance_pence=? WHERE account_no=?", (src_new, source))
            db.execute("UPDATE accounts SET balance_pence=? WHERE account_no=?", (dst_new, destination))
            self._record_tx(db, source, "TRANSFER_OUT", pence, src_new, actor.user_id, note, destination, ref)
            self._record_tx(db, destination, "TRANSFER_IN", pence, dst_new, actor.user_id, note, source, ref)
            self._audit(db, actor.user_id, "TRANSFER", f"{source} → {destination}", {"pence": pence, "ref": ref})
            return ref

    def transactions(self, actor: Session, account_no: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
        self._require(actor)
        limit = max(1, min(int(limit), 2000))
        if account_no is not None:
            self._account(self.conn, account_no, active=False)
            sql = "SELECT t.*,u.username AS actor FROM transactions t LEFT JOIN users u ON t.actor_id=u.id WHERE account_no=? ORDER BY t.id DESC LIMIT ?"
            rows = self.conn.execute(sql, (account_no, limit))
        else:
            sql = "SELECT t.*,u.username AS actor FROM transactions t LEFT JOIN users u ON t.actor_id=u.id ORDER BY t.id DESC LIMIT ?"
            rows = self.conn.execute(sql, (limit,))
        return [dict(row) for row in rows]

    def dashboard(self, actor: Session) -> dict[str, Any]:
        self._require(actor)
        row = self.conn.execute("SELECT COUNT(*) AS total, "
                                "SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS active, "
                                "COALESCE(SUM(balance_pence),0) AS money FROM accounts").fetchone()
        count_tx = self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        return {"total": row["total"], "active": row["active"], "money": row["money"], "transactions": count_tx}

    def audit_log(self, actor: Session, limit: int = 500) -> list[dict[str, Any]]:
        self._require(actor, "admin")
        return [dict(r) for r in self.conn.execute(
            "SELECT a.id,a.created_at,COALESCE(u.username,'system') AS actor,a.event,a.target,a.details "
            "FROM audit_log a LEFT JOIN users u ON a.actor_id=u.id ORDER BY a.id DESC LIMIT ?",
            (min(max(int(limit), 1), 2000),))]

    def backup_database(self, actor: Session, destination: str | Path) -> Path:
        self._require(actor, "admin")
        target = Path(destination).expanduser().resolve()
        if target == self.path:
            raise BankError("Backup path must differ from the live database.")
        if target.exists():
            raise BankError("Destination already exists; choose a new filename.")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(target) as out:
                self.conn.backup(out)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        with self._tx() as db:
            self._audit(db, actor.user_id, "BACKUP_CREATED", target.name)
        return target


def export_csv(path: str | Path, columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
    """Write caller-selected database fields without unsafe spreadsheet formulas."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([heading for _key, heading in columns])
        for row in rows:
            writer.writerow([_csv_safe(row.get(key, "")) for key, _heading in columns])
