"""Run: python -m unittest -v test_bank_manager.py"""
from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import AccessDenied, BankDB, BankError, export_csv, parse_money, pounds


class BankManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bankmanaging.db"
        self.db = BankDB(self.path)
        self.db.create_initial_admin("owner", "a very long password 2026")
        self.admin = self.db.authenticate("owner", "a very long password 2026")
        self.emp_id = self.db.create_employee(self.admin, "cashier", "temporary test password",
                                              "1200.00", "Cashier")
        self.temp_employee = self.db.authenticate("cashier", "temporary test password")
        self.employee = self.db.change_own_password(self.temp_employee, "temporary test password",
                                                   "employee new password")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_money_precision_and_rejection(self):
        self.assertEqual(parse_money("0.01"), 1)
        self.assertEqual(parse_money("100.99"), 10099)
        self.assertEqual(pounds(10099), "£100.99")
        for bad in ("-2", "+1", "1.001", "1e3", "  ", "nan", "1,000", "0.000"):
            with self.subTest(amount=bad), self.assertRaises(BankError):
                parse_money(bad)

    def test_create_update_search_and_close(self):
        acc = self.db.create_account(self.employee, "Jane Smith", "28", "High Street",
                                     "12.50", "Savings", "07123456789")
        self.assertEqual(self.db.get_account(self.employee, acc)["balance_pence"], 1250)
        self.db.update_account(self.employee, acc, name="Jane O'Connor", age="29",
                               address="House 1", account_type="Current", phone="07123456789")
        self.assertEqual(len(self.db.list_accounts(self.employee, "O'Connor")), 1)
        with self.assertRaises(BankError):
            self.db.close_account(self.employee, acc)
        self.db.withdraw(self.employee, acc, "12.50")
        self.db.close_account(self.employee, acc)
        self.assertEqual(len(self.db.list_accounts(self.employee)), 0)
        self.assertEqual(len(self.db.list_accounts(self.employee, include_closed=True)), 1)
        with self.assertRaises(BankError):
            self.db.deposit(self.employee, acc, "1")
        with self.assertRaises(AccessDenied):
            self.db.reopen_account(self.employee, acc)
        self.db.reopen_account(self.admin, acc)
        self.assertEqual(self.db.get_account(self.admin, acc)["status"], "ACTIVE")

    def test_deposit_withdraw_and_no_negative_money(self):
        acc = self.db.create_account(self.admin, "Test", "30", "Road", "20", "Current", "07123456789")
        self.assertEqual(self.db.deposit(self.employee, acc, "0.10"), 2010)
        self.assertEqual(self.db.withdraw(self.employee, acc, "10.05"), 1005)
        with self.assertRaises(BankError):
            self.db.withdraw(self.employee, acc, "15")
        with self.assertRaises(BankError):
            self.db.withdraw(self.employee, acc, "-1")
        with self.assertRaises(BankError):
            self.db.deposit(self.employee, acc, "0")
        self.assertEqual(self.db.get_account(self.admin, acc)["balance_pence"], 1005)
        entries = self.db.transactions(self.admin, acc)
        self.assertEqual([r["kind"] for r in entries], ["WITHDRAWAL", "DEPOSIT", "OPENING"])

    def test_transfer_atomicity_and_ledger(self):
        a = self.db.create_account(self.admin, "A", "20", "Road", "12.00", "Current", "07123456789")
        b = self.db.create_account(self.admin, "B", "21", "Road", "1.50", "Current", "07123456789")
        ref = self.db.transfer(self.employee, a, b, "2.25", "invoice")
        self.assertEqual(self.db.get_account(self.admin, a)["balance_pence"], 975)
        self.assertEqual(self.db.get_account(self.admin, b)["balance_pence"], 375)
        self.assertEqual(self.db.transactions(self.admin, a)[0]["transfer_ref"], ref)
        self.assertEqual(self.db.transactions(self.admin, b)[0]["transfer_ref"], ref)
        with self.assertRaises(BankError):
            self.db.transfer(self.employee, a, b, "10000")
        with self.assertRaises(BankError):
            self.db.transfer(self.employee, a, 99999, "1")
        with self.assertRaises(BankError):
            self.db.transfer(self.employee, a, a, "1")
        self.assertEqual(self.db.get_account(self.admin, a)["balance_pence"], 975)
        self.assertEqual(self.db.get_account(self.admin, b)["balance_pence"], 375)
        self.assertEqual(len(self.db.transactions(self.admin, b)), 2)

    def test_access_passwords_and_employee_management(self):
        with self.assertRaises(AccessDenied):
            self.db.list_employees(self.employee)
        with self.assertRaises(AccessDenied):
            self.db.audit_log(self.employee)
        with self.assertRaises(AccessDenied):
            self.db.create_account(self.temp_employee, "X", "20", "Addr", "1", "A", "07123456789")
        with self.assertRaises(AccessDenied):
            self.db.authenticate("cashier", "bad password")
        self.db.update_employee(self.admin, self.emp_id, username="cashier2", salary="1300.10",
                                position="Supervisor", active=True)
        with self.assertRaises(AccessDenied):
            self.db.list_accounts(self.employee)
        self.db.reset_employee_password(self.admin, self.emp_id, "another temporary password")
        changed = self.db.authenticate("cashier2", "another temporary password")
        self.assertTrue(changed.must_change_password)
        self.db.update_employee(self.admin, self.emp_id, username="cashier2", salary="1300.10",
                                position="Supervisor", active=False)
        with self.assertRaises(AccessDenied):
            self.db.authenticate("cashier2", "another temporary password")
        users = self.db.list_employees(self.admin)
        self.assertNotIn("password_hash", users[0])

    def test_login_lockout(self):
        for i in range(5):
            with self.assertRaises(AccessDenied):
                self.db.authenticate("cashier", "bad")
        with self.assertRaisesRegex(AccessDenied, "locked"):
            self.db.authenticate("cashier", "employee new password")
        locked_until = self.db.conn.execute("SELECT locked_until FROM users WHERE id=?", (self.emp_id,)).fetchone()[0]
        self.assertIsNotNone(locked_until)

    def test_sql_injection_and_csv_escape(self):
        a = self.db.create_account(self.admin, "Alice'); DROP TABLE accounts;--", "20", "Safe Road",
                                   "1.00", "Savings", "07123456789")
        self.db.update_account(self.admin, a, name="=1+1", age="22", address="A'B",
                               account_type="Current", phone="07123456789")
        self.assertIsNotNone(self.db.get_account(self.admin, a))
        target = Path(self.temp.name) / "export.csv"
        export_csv(target, [("full_name", "Name")], self.db.list_accounts(self.admin))
        with target.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[1][0], "'=1+1")

    def test_backup_and_persistence(self):
        a = self.db.create_account(self.admin, "Person", "42", "Street", "3.25", "Current", "07123456789")
        target = Path(self.temp.name) / "safe-backup.db"
        self.db.backup_database(self.admin, target)
        with sqlite3.connect(target) as db2:
            self.assertEqual(db2.execute("SELECT balance_pence FROM accounts WHERE account_no=?", (a,)).fetchone()[0], 325)
        self.db.close()
        self.db = BankDB(self.path)
        admin2 = self.db.authenticate("owner", "a very long password 2026")
        self.assertEqual(self.db.get_account(admin2, a)["balance_pence"], 325)
        with self.assertRaises(BankError):
            self.db.backup_database(admin2, target)


class MigrationTests(unittest.TestCase):
    def test_legacy_round_trip_and_plaintext_removal(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bankmanaging.db"
            with sqlite3.connect(path) as conn:
                conn.executescript('''
                    CREATE TABLE bank(acc_no int,name text,age int,address text,balance int,account_type text,mobile_number int);
                    CREATE TABLE staff(name text,"pass" text,salary int,position text);
                    CREATE TABLE admin(name text,"pass" text);
                    INSERT INTO admin VALUES('arpit','123');
                    INSERT INTO admin VALUES('arpit','123');
                    INSERT INTO staff VALUES('steve','staff-pass',500,'Teller');
                    INSERT INTO bank VALUES(7,'Nina',35,'Main',150,'Savings',7123456789);
                ''')
            db = BankDB(path)
            try:
                self.assertIsNotNone(db.migration_backup)
                self.assertTrue(db.migration_backup.exists())
                self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 1)
                self.assertFalse(db._table_exists("admin"))
                admin = db.authenticate("arpit", "123")
                self.assertTrue(admin.must_change_password)
                with self.assertRaises(AccessDenied):
                    db.get_account(admin, 7)
                admin = db.change_own_password(admin, "123", "new secure password")
                self.assertEqual(db.get_account(admin, 7)["balance_pence"], 15000)
                self.assertEqual(db.transactions(admin, 7)[0]["kind"], "OPENING")
                emp = db.authenticate("steve", "staff-pass")
                self.assertTrue(emp.must_change_password)
            finally:
                db.close()

    def test_migration_failure_does_not_delete_original(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bankmanaging.db"
            with sqlite3.connect(path) as conn:
                conn.executescript('''
                    CREATE TABLE bank(acc_no int,name text,age int,address text,balance int,account_type text,mobile_number int);
                    INSERT INTO bank VALUES(1,'X',20,'Road',-4,'Current',1234567);
                ''')
            with self.assertRaises(BankError):
                BankDB(path)
            with sqlite3.connect(path) as c:
                self.assertEqual(c.execute("SELECT balance FROM bank").fetchone()[0], -4)


if __name__ == "__main__":
    unittest.main()
