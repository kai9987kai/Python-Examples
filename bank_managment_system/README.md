# Bank Manager Desktop 2.0

An offline, educational banking-management application written in **Python 3 + Tkinter + SQLite**. It replaces a legacy two-script banking GUI while preserving the essential admin, employee, and customer workflows, and adds a ledger, internal transfers, migration, reports, stronger authentication, searchable tables, and backups.

> **Important:** This is a classroom/portfolio simulation, **not a real bank, payment processor, accounting system, or production-ready financial service**. There is no integration with external banks, card schemes, identity-verification services, or payment rails. Balances represent fictional GBP amounts, not actual money. SQLite files and exported CSVs are **not encrypted**.

## Files

```text
bank_manager_upgrade/
├── frontend.py           # Tkinter user interface and forms
├── backend.py            # Database, authentication, business logic, ledger, migration
├── test_bank_manager.py  # Backend regression tests
└── README.md             # This documentation

# Created automatically on first run, alongside backend.py:
# bankmanaging.db          (SQLite; do not commit to source control)
# bankmanaging.db-wal      (may appear while open)
# bankmanaging.db-shm      (may appear while open)
```

The program uses the **Python standard library only**. No `pip install` is needed when your Python installation includes Tkinter. On some Linux distributions you may need to install the system `python3-tk` package. Python **3.10 or later** is required (3.12+ recommended).

## Quick start

1. Keep `frontend.py` and `backend.py` in the same folder.
2. In that folder, run:

   ```bash
   python frontend.py
   ```

   On Windows, `py frontend.py` also works. On some Linux systems, use `python3 frontend.py`.
3. On first run with a new database, create the first administrator. Choose a username and a password of **at least 12 characters**. **There is no shipped default password.**
4. Sign in as administrator. Create an employee under **Employees**, assigning a temporary password. The employee must change that password on first sign-in.
5. Create a customer account under **Accounts → Create**, then use **Money**, **Transfers**, and **History** to manage fictional balances.

Choose a separate database, useful for testing, with:

```bash
python frontend.py --db "C:\Users\Public\Documents\demo-bank.db"
```

On Linux/macOS use a platform-appropriate filesystem path.

## Original-feature parity

| Original workflow | Updated implementation |
| --- | --- |
| Admin sign-in | Admin sign-in with salted password hashing and lockout |
| Employee sign-in | Employee sign-in with secure password verification |
| Create employee | **Employees → Create employee** |
| Show all employees | **Employees** searchable/sortable table presentation (sort by heading) |
| Update employee name, password, salary, position | **Employees → Edit employee** or **Reset password** |
| Total customer money | **Dashboard → Total balances** |
| Create customer account | **Accounts → Create** |
| Find customer by account number | **Accounts → Search** or **View details** |
| View full customer details | Double-click an account or **View details** |
| Add money | **Money → Deposit** |
| Withdraw money | **Money → Withdraw** with overdraft prevention |
| Check balance | **Money → Check balance**, **Accounts**, or **Dashboard** |
| Update customer name, age, address | **Accounts → Edit**; also edits account type and phone |
| List all customers | **Accounts** table, now with search, sorting, optional closed accounts |
| Delete customer account | **Accounts → Close** (soft deletion, only if balance is zero) |
| Sign out / exit | Persistent sidebar controls |

**Intentional behavioral changes:** Deleting a customer no longer irreversibly erases balances and history; it **closes** a zero-balance account and retains a complete ledger. Only an administrator can reopen it. Employee passwords are never displayed (the original listed them in plaintext). Saving invalid or negative money amounts is disallowed. These restrictions improve data integrity, but they mean the program is **not identical in behavior** to the old version.

## Additional capabilities

- **Transaction ledger:** Each opening balance, deposit, withdrawal, and internal transfer gets an immutable-by-UI ledger entry recording the UTC date, action, account, positive amount, resulting balance, optional note and staff ID.
- **Atomic transfers:** Source debit and destination credit happen in the same SQLite `BEGIN IMMEDIATE` transaction, with a shared transfer reference; failed transfers are rolled back.
- **Audit trail:** Admin-only history of creation, updates, account closures, transfers, authentication, password changes, and backups.
- **Data protection at application level:** Parameterized SQL instead of SQL string interpolation; role checks in the backend, not only in the GUI; scrypt salted password hashes; per-user login lockout after five consecutive failures for 15 minutes; temporary password rotation; session invalidation after a password change, password reset, or employee edit.
- **Exact money calculations:** Internal balances, payments, and salaries are stored in **integer pence**, not floats. Form inputs accept `0`, `0.01`, `125`, or `125.30`, with up to two fractional digits. Deposits/withdrawals/transfers must be strictly positive. Per-account and per-operation demonstration limit: **£1,000,000,000.00**.
- **User experience:** Modern `ttk` dark appearance; resizable window; scrollable, sortable tables; modal validation messages; confirmation dialogs; dashboard metrics; customer search by number, name, phone or account type.
- **History and export:** View recent transactions (500 by default), filter by account, export up to 2,000 transaction records as UTF-8 CSV. Account CSV export is available to admins.
- **Backup:** Admins can make a consistent SQLite snapshot through the SQLite backup API in Settings.
- **Fewer globals:** Frontend controls use class state and `StringVar`; the backend uses a dedicated `BankDB` instance and explicit session objects.

## Legacy `bankmanaging.db` migration

This project detects the **exact three legacy tables** in the old version: `bank`, `staff` and `admin`. If an existing SQLite file with those tables is in the backend folder, the program attempts a **one-time, transactional import** on startup:

1. Before schema changes, it writes a timestamped copy such as `bankmanaging.legacy-backup-20261017T061600Z-a1b2c3.db` using SQLite's backup API.
2. Migrates admin and staff credentials to salted scrypt hashes; **forces password changes at the next login**.
3. Imports customers, preserves account numbers, and creates an opening ledger record for each imported balance.
4. Drops the old plaintext credential tables from the **live upgraded database after a successful import**. The original backup is left intact for recovery.

**Very important assumptions and caveats:**

- An original numeric `balance` of `150` is interpreted as **£150.00** (15,000 pence), **not £1.50**. Salaries are interpreted similarly. Check this matches how you used the old software before migrating real historical demo data.
- Original phone numbers were stored as integers. If a phone number's leading zero was previously lost, the new code cannot reconstruct it automatically. Edit it in Accounts after migration.
- Legacy records with duplicate usernames are renamed as needed using `_staff_1`, etc. Two identical admin usernames are imported only once. Review employee usernames afterward.
- An insecure admin entry such as `arpit` / `123` will **not be created in new databases**. But if present in an *existing legacy database*, it can be used **once to sign in to the imported admin**, after which the app requires a new 12+ character password. Change it immediately and protect/delete the *unencrypted legacy backup* only after you have verified recovery requirements.
- Import will deliberately stop on an invalid or duplicate account number, negative balance, or unrepresentable legacy money amount. The migration error identifies the issue. Do **not** delete the backup. Correct a **separate working copy** of the legacy file, not your only original, before retrying.
- This migration targets the pasted legacy database layout. It does **not** provide a generic converter for arbitrary modified schemas.

## Operational guidance

### Admin

Admins can manage employees, review audit events, export customer directories, create backups, reopen closed accounts, and use every customer banking workflow. An administrator cannot create another admin within the GUI; first-time admin setup is permitted only if there is no admin account.

### Employee

Employees can create/search/update customer accounts; deposit, withdraw, check balances, transfer between accounts, review transactions, and close **zero-balance** accounts. Employees cannot manage other users, reopen closed accounts, or view the audit log.

### Closing an account

1. Check that the balance is zero. If it is nonzero, **withdraw** the remaining fictional amount or transfer it elsewhere first.
2. Select the account in **Accounts**, then click **Close**, confirm, and the status becomes `CLOSED`.
3. By default, closed accounts are hidden. Tick **Show closed** to view them. Admins can select a closed account and click **Reopen**.

### Backing up safely

Use **Settings → Backup SQLite database**. The backup API takes a database-consistent snapshot even when SQLite uses WAL journaling. Backups/exports remain readable SQLite/CSV files and can contain names, addresses, phone numbers, password hashes, and ledger data. Store them in a restricted-access or encrypted folder, avoid public repositories, and do not send them in public bug reports.

For a full restore, close the application, keep the current database as a separate safety copy, then replace the database file with the backup. Do not replace the file while the app is running. Use fresh passwords if restoring an old snapshot.

## Security architecture and limits

| Risk | Defense in this version | Remaining limitation |
| --- | --- | --- |
| SQL injection | Parameterized input queries; no untrusted values used as SQL syntax | Not a full penetration-tested system |
| Password exposure | Per-user salted memory-hard scrypt hashes; password masking; no password column in employee lists | Database is unencrypted; compromised local system can access hashed credentials |
| Guessing passwords | 5-failure / 15-minute account lockout | Not a network-facing rate limiter; lockout can be abused for denial-of-service |
| Financial calculation error | Decimal parsing → integer pence; CHECK constraints; explicit money bounds | Legacy money-unit interpretation must be checked |
| Partial multi-account transactions | SQLite transactions with `BEGIN IMMEDIATE` and rollback | Not a distributed financial ledger or settlement engine |
| Data deletion | Soft-close of zero-balance accounts | Database administrators can modify SQLite files outside the app |
| Privilege escalation through UI | Backend session and admin permission checks | No operating-system user isolation; a local user with unrestricted DB write access could alter roles |
| Dangerous spreadsheet formulas | Best-effort escaping for potentially formula-like CSV text | No CSV escaping method is universally safe across all spreadsheet programs and re-save workflows |
| Database loss | On-demand consistent backups; pre-migration snapshot | No automatic offsite backups, encryption, disaster recovery or key management |

**Research-informed choices:**

- OWASP Password Storage Cheat Sheet (Argon2id preferred; scrypt a strong standard-library alternative): https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- Python `sqlite3` reference: https://docs.python.org/3/library/sqlite3.html
- SQLite Online Backup API: https://www.sqlite.org/backup.html
- OWASP CSV Injection: https://owasp.org/www-community/attacks/CSV_Injection
- Python `ttk` reference: https://docs.python.org/3/library/tkinter.ttk.html

**This is not a proof of production security or regulatory compliance.** Real financial systems would additionally need strong OS-level data-access controls, encrypted sensitive fields or volumes, multi-factor authentication, safer account recovery, stronger audit integrity guarantees, independent ledgers and reconciliation, observability, extensive threat modeling and penetration testing, disaster recovery, data retention policies, and relevant UK regulatory compliance.

## Running regression tests

From the folder containing the files:

```bash
python -m unittest -v test_bank_manager.py
```

The tests use separate temporary SQLite databases. They verify:

- exact decimal-to-pence conversion and invalid amount rejection;
- customer creation, search, updating, closure, and admin reopening;
- deposits/withdrawals, insufficient funds, and ledger records;
- atomic transfers, matching references and failure rollback;
- admin/employee roles, staff changes, password resets and session invalidation;
- login lockouts, SQL-injection resistance, CSV escaping;
- SQLite backup and reopen persistence;
- successful old-table migration and safe preservation on failed migration.

These tests exercise backend functions. They do **not** certify the UI on every operating system, accessibility with assistive technology, heavy-load throughput, or production security. GUI rendering must still be visually inspected on your own Windows/Linux/macOS computer.

## Suggested `.gitignore`

```gitignore
__pycache__/
*.py[cod]
.venv/
*.db
*.db-wal
*.db-shm
*.csv
*.bak
```

## Example flow

```text
Admin creates a teller employee
    ↓
Employee signs in and changes their temporary password
    ↓
Employee creates account #1 with £100.00 opening balance
    ↓
Employee creates account #2 with £0.00 opening balance
    ↓
Employee transfers £25.00 from #1 → #2
    ↓
Balances: #1 £75.00, #2 £25.00
    ↓
History: transfer out + transfer in, same transfer reference
    ↓
Admin can see total fictional bank balances of £100.00
```

## License and attribution

This is a reimplementation of the supplied example, with major architectural, usability, security, and test improvements. Add a `LICENSE` file if you intend to distribute it under a specific license, and respect any license obligations associated with the original code if it originated from a third-party repository.
