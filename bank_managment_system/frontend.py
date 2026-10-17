"""Bank Manager modern Tkinter interface. Run: python frontend.py [--db PATH]"""
from __future__ import annotations

import argparse
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from backend import (AccessDenied, BankDB, BankError, Session, export_csv,
                     pounds)

BG = "#0c1425"
PANEL = "#14223a"
PANEL2 = "#1b2d48"
EDGE = "#30445f"
FG = "#f1f5fc"
MUTED = "#a6bad2"
PRIMARY = "#58a6ff"
GOOD = "#46d6a0"
WARN = "#ff8b8b"
FONT = "Segoe UI"


class FormDialog(tk.Toplevel):
    """Simple modal data-entry form with field-level show-password handling."""
    def __init__(self, parent: tk.Tk, title: str,
                 fields: list[tuple[str, str, str, bool]],
                 on_save: Callable[[dict[str, str]], None],
                 description: str = ""):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.transient(parent)
        self.on_save = on_save
        self.vars: dict[str, tk.StringVar] = {}
        inner = ttk.Frame(self, padding=24)
        inner.pack(fill="both", expand=True)
        ttk.Label(inner, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        if description:
            ttk.Label(inner, text=description, style="Muted.TLabel", wraplength=430).pack(anchor="w", pady=(0, 12))
        first: ttk.Entry | None = None
        for key, label, initial, hidden in fields:
            ttk.Label(inner, text=label).pack(anchor="w", pady=(9, 4))
            var = tk.StringVar(value=initial)
            self.vars[key] = var
            inp = ttk.Entry(inner, textvariable=var, width=55, show="•" if hidden else "")
            inp.pack(fill="x")
            if first is None:
                first = inp
        controls = ttk.Frame(inner)
        controls.pack(fill="x", pady=(22, 0))
        ttk.Button(controls, text="Cancel", command=self.destroy).pack(side="right", padx=(9, 0))
        ttk.Button(controls, text="Save", style="Accent.TButton", command=self._submit).pack(side="right")
        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        if first:
            first.focus_set()
        self.update_idletasks()
        self.geometry(f"+{max(0, parent.winfo_rootx() + 90)}+{max(0, parent.winfo_rooty() + 60)}")

    def _submit(self) -> None:
        try:
            self.on_save({k: v.get() for k, v in self.vars.items()})
        except (BankError, sqlite3.Error, ValueError) as exc:
            messagebox.showerror("Unable to save", str(exc), parent=self)
        else:
            if self.winfo_exists():
                self.destroy()


class BankApp:
    def __init__(self, database: BankDB):
        self.db = database
        self.root = tk.Tk()
        self.root.title("Bank Manager | Desktop")
        self.root.geometry("1280x820")
        self.root.minsize(1030, 660)
        self.root.configure(bg=BG)
        self.session: Session | None = None
        self.current_page = ""
        self._style()
        self.root.protocol("WM_DELETE_WINDOW", self.exit)
        self.show_login()

    def _style(self) -> None:
        sty = ttk.Style(self.root)
        sty.theme_use("clam")
        sty.configure("TFrame", background=PANEL)
        sty.configure("App.TFrame", background=BG)
        sty.configure("Side.TFrame", background=PANEL)
        sty.configure("TLabel", background=PANEL, foreground=FG, font=(FONT, 10))
        sty.configure("Title.TLabel", background=PANEL, foreground=FG, font=(FONT, 19, "bold"))
        sty.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 10))
        sty.configure("Big.TLabel", background=PANEL, foreground=FG, font=(FONT, 24, "bold"))
        sty.configure("Header.TLabel", background=BG, foreground=FG, font=(FONT, 22, "bold"))
        sty.configure("HeaderSub.TLabel", background=BG, foreground=MUTED, font=(FONT, 10))
        sty.configure("TEntry", fieldbackground=PANEL2, foreground=FG, insertcolor=FG, bordercolor=EDGE,
                      padding=(9, 8))
        sty.configure("TCombobox", fieldbackground=PANEL2, foreground=FG, background=PANEL2,
                      arrowcolor=FG, padding=(9, 7))
        sty.configure("TButton", font=(FONT, 10, "bold"), padding=(14, 10),
                      background=PANEL2, foreground=FG, bordercolor=EDGE)
        sty.map("TButton", background=[("active", EDGE)], foreground=[("disabled", MUTED)])
        sty.configure("Accent.TButton", background=PRIMARY, foreground="#07162a", bordercolor=PRIMARY)
        sty.map("Accent.TButton", background=[("active", "#8bc1ff")])
        sty.configure("Danger.TButton", background="#793247", foreground=FG, bordercolor="#793247")
        sty.map("Danger.TButton", background=[("active", "#a3435c")])
        sty.configure("TCheckbutton", background=PANEL, foreground=FG)
        sty.configure("Treeview", background=PANEL, foreground=FG, fieldbackground=PANEL,
                      rowheight=33, borderwidth=0, font=(FONT, 10))
        sty.configure("Treeview.Heading", background=PANEL2, foreground=FG, padding=(10, 9),
                      font=(FONT, 10, "bold"))
        sty.map("Treeview", background=[("selected", "#24507b")], foreground=[("selected", FG)])
        sty.map("Treeview.Heading", background=[("active", EDGE)])
        sty.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=PANEL)
        sty.configure("Horizontal.TScrollbar", background=PANEL2, troughcolor=PANEL)

    def _clear(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (BankError, sqlite3.Error, ValueError) as exc:
            messagebox.showerror("Action not completed", str(exc), parent=self.root)
            return None

    def _auth_panel(self, title: str, subtitle: str) -> ttk.Frame:
        self._clear()
        outer = ttk.Frame(self.root, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        frame = ttk.Frame(outer, padding=42)
        frame.place(relx=.5, rely=.48, anchor="center", width=500)
        ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(frame, text=subtitle, style="Muted.TLabel", wraplength=400).pack(anchor="w", pady=(0, 28))
        return frame

    def show_login(self) -> None:
        self.session = None
        if self.db.needs_admin_setup():
            self.show_setup()
            return
        frame = self._auth_panel("BANK MANAGER", "Secure, local-only educational banking dashboard")
        ttk.Label(frame, text="Username").pack(anchor="w", pady=(0, 6))
        username = tk.StringVar()
        inp = ttk.Entry(frame, textvariable=username)
        inp.pack(fill="x", pady=(0, 17))
        ttk.Label(frame, text="Password").pack(anchor="w", pady=(0, 6))
        password = tk.StringVar()
        pw = ttk.Entry(frame, textvariable=password, show="•")
        pw.pack(fill="x", pady=(0, 24))

        def login() -> None:
            session = self._call(self.db.authenticate, username.get(), password.get())
            password.set("")
            if isinstance(session, Session):
                self.session = session
                if session.must_change_password:
                    self.show_password_change(required=True)
                else:
                    self.navigate("Dashboard")

        ttk.Button(frame, text="Sign in", style="Accent.TButton", command=login).pack(fill="x")
        ttk.Label(frame, text="Offline SQLite demo · No online banking connection", style="Muted.TLabel").pack(anchor="w", pady=(24, 0))
        pw.bind("<Return>", lambda _e: login())
        inp.focus_set()

    def show_setup(self) -> None:
        frame = self._auth_panel("FIRST-RUN SETUP", "Create an administrator. No default administrator password is installed.")
        vars_: dict[str, tk.StringVar] = {}
        for key, label, hidden in (("username", "Administrator username", False),
                                   ("password", "Password (at least 12 characters)", True),
                                   ("confirm", "Confirm password", True)):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(11, 6))
            var = tk.StringVar()
            vars_[key] = var
            ttk.Entry(frame, textvariable=var, show="•" if hidden else "").pack(fill="x")

        def save() -> None:
            if vars_["password"].get() != vars_["confirm"].get():
                messagebox.showerror("Passwords differ", "The passwords must match.", parent=self.root)
                return
            if self._call(self.db.create_initial_admin, vars_["username"].get(), vars_["password"].get()) is None:
                # A successful create method returns None too: inspect DB state.
                if self.db.needs_admin_setup():
                    return
            messagebox.showinfo("Administrator created", "You can now sign in.", parent=self.root)
            self.show_login()

        ttk.Button(frame, text="Create administrator", style="Accent.TButton", command=save).pack(fill="x", pady=(24, 0))

    def show_password_change(self, required: bool = False) -> None:
        assert self.session
        session = self.session
        if required:
            frame = self._auth_panel("PASSWORD UPDATE REQUIRED", "Your migrated or temporary password must be replaced before you can access the dashboard.")
        else:
            self._layout("Settings")
            frame = ttk.Frame(self.content, padding=22)
            frame.pack(anchor="nw", fill="x", pady=12)
            ttk.Label(frame, text="Change your password", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        values: dict[str, tk.StringVar] = {}
        for key, label in (("old", "Current password"), ("new", "New password (12+ characters)"),
                           ("confirm", "Confirm new password")):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(12, 5))
            v = tk.StringVar()
            values[key] = v
            ttk.Entry(frame, textvariable=v, show="•", width=48).pack(anchor="w", fill="x")

        def change() -> None:
            if values["new"].get() != values["confirm"].get():
                messagebox.showerror("Password mismatch", "New passwords do not match.", parent=self.root)
                return
            changed = self._call(self.db.change_own_password, session, values["old"].get(), values["new"].get())
            if isinstance(changed, Session):
                self.session = changed
                messagebox.showinfo("Updated", "Password changed successfully.", parent=self.root)
                self.navigate("Dashboard" if required else "Settings")

        ttk.Button(frame, text="Update password", style="Accent.TButton", command=change).pack(anchor="w", pady=(22, 0))
        if required:
            ttk.Button(frame, text="Sign out", command=self.show_login).pack(anchor="w", pady=(12, 0))

    def _layout(self, page: str) -> None:
        assert self.session is not None
        self._clear()
        layout = ttk.Frame(self.root, style="App.TFrame")
        layout.pack(fill="both", expand=True)
        side = ttk.Frame(layout, style="Side.TFrame", padding=(18, 26))
        side.pack(side="left", fill="y")
        ttk.Label(side, text="BANK MANAGER", style="Title.TLabel").pack(anchor="w", pady=(2, 7))
        ttk.Label(side, text=f"{self.session.username}  ·  {self.session.role.title()}",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 26))
        pages = ["Dashboard", "Accounts", "Money", "Transfers", "History"]
        if self.session.role == "admin":
            pages += ["Employees", "Audit log"]
        pages += ["Settings"]
        for label in pages:
            ttk.Button(side, text=label, style="Accent.TButton" if label == page else "TButton",
                       command=lambda p=label: self.navigate(p)).pack(fill="x", pady=4)
        ttk.Separator(side).pack(fill="x", pady=(24, 15))
        ttk.Button(side, text="Sign out", command=self.show_login).pack(fill="x", pady=4)
        ttk.Button(side, text="Exit", command=self.exit).pack(fill="x", pady=4)
        right = ttk.Frame(layout, style="App.TFrame", padding=(26, 24))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text=page, style="Header.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(right, text="Offline account management · GBP demonstration balances",
                  style="HeaderSub.TLabel").pack(anchor="w", pady=(0, 18))
        self.content = ttk.Frame(right, style="App.TFrame")
        self.content.pack(fill="both", expand=True)
        self.current_page = page

    def navigate(self, page: str) -> None:
        self._layout(page)
        views = {
            "Dashboard": self.show_dashboard, "Accounts": self.show_accounts,
            "Money": self.show_money, "Transfers": self.show_transfers,
            "History": self.show_history, "Employees": self.show_employees,
            "Audit log": self.show_audit, "Settings": self.show_settings,
        }
        self._call(views[page])

    def _section(self, parent: ttk.Frame | None = None, padding: int = 20) -> ttk.Frame:
        wrapper = ttk.Frame(parent or self.content, padding=padding)
        wrapper.pack(fill="both", expand=True, pady=(0, 10))
        return wrapper

    def _buttons(self, parent: ttk.Frame, specs: list[tuple[str, Callable[[], None], str]]) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 16))
        for label, command, style in specs:
            ttk.Button(row, text=label, command=command, style=style).pack(side="left", padx=(0, 8))
        return row

    def _tree(self, parent: ttk.Frame, columns: list[tuple[str, str, int]], height: int = 15) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        keys = [x[0] for x in columns]
        tree = ttk.Treeview(holder, columns=keys, show="headings", selectmode="browse", height=height)
        for key, label, width in columns:
            tree.heading(key, text=label, command=lambda c=key: self._sort_tree(tree, c, False))
            tree.column(key, width=width, minwidth=60, stretch=True, anchor="w")
        scrolly = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        scrollx = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scrolly.set, xscrollcommand=scrollx.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrolly.grid(row=0, column=1, sticky="ns")
        scrollx.grid(row=1, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        return tree

    def _sort_tree(self, tree: ttk.Treeview, key: str, reverse: bool) -> None:
        values = [(tree.set(i, key), i) for i in tree.get_children("")]
        def sortable(item: tuple[str, str]):
            raw = item[0].replace("£", "").replace(",", "").strip()
            try:
                return (0, float(raw))
            except ValueError:
                return (1, item[0].casefold())
        for idx, (_, iid) in enumerate(sorted(values, key=sortable, reverse=reverse)):
            tree.move(iid, "", idx)
        tree.heading(key, command=lambda: self._sort_tree(tree, key, not reverse))

    def show_dashboard(self) -> None:
        assert self.session
        summary = self.db.dashboard(self.session)
        row = ttk.Frame(self.content, style="App.TFrame")
        row.pack(fill="x", pady=(0, 16))
        for title, value in (("Total balances", pounds(summary["money"])),
                             ("Active accounts", str(summary["active"])),
                             ("All accounts", str(summary["total"])),
                             ("Ledger entries", str(summary["transactions"]))):
            card = ttk.Frame(row, padding=20)
            card.pack(side="left", fill="x", expand=True, padx=(0, 12))
            ttk.Label(card, text=title, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(card, text=value, style="Big.TLabel").pack(anchor="w", pady=(12, 0))
        panel = self._section()
        ttk.Label(panel, text="Quick actions", style="Title.TLabel").pack(anchor="w", pady=(0, 14))
        self._buttons(panel, [("New account", self.new_account, "Accent.TButton"),
                              ("Deposit / withdraw", lambda: self.navigate("Money"), "TButton"),
                              ("Transfer funds", lambda: self.navigate("Transfers"), "TButton"),
                              ("View account directory", lambda: self.navigate("Accounts"), "TButton")])
        ttk.Label(panel, text="Recent account activity", style="Muted.TLabel").pack(anchor="w", pady=(16, 9))
        tree = self._tree(panel, [("time", "UTC time", 180), ("account", "Account", 90),
                                  ("type", "Type", 150), ("amount", "Amount", 140),
                                  ("balance", "New balance", 145)], height=12)
        for r in self.db.transactions(self.session, limit=25):
            tree.insert("", "end", values=(r["created_at"][:19].replace("T", " "), r["account_no"],
                                             r["kind"].replace("_", " ").title(), pounds(r["amount_pence"]),
                                             pounds(r["balance_after_pence"])))

    def _selected(self, tree: ttk.Treeview) -> int | None:
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select an entry", "Select a row first.", parent=self.root)
            return None
        return int(selected[0])

    def show_accounts(self) -> None:
        assert self.session
        panel = self._section()
        search_bar = ttk.Frame(panel)
        search_bar.pack(fill="x", pady=(0, 14))
        ttk.Label(search_bar, text="Find account by number, name, type or phone").pack(side="left", padx=(0, 12))
        query = tk.StringVar()
        inp = ttk.Entry(search_bar, textvariable=query, width=26)
        inp.pack(side="left", padx=(0, 8))
        closed = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_bar, text="Show closed", variable=closed).pack(side="left", padx=(6, 12))
        tree: ttk.Treeview

        def refresh() -> None:
            for iid in tree.get_children():
                tree.delete(iid)
            for r in self.db.list_accounts(self.session, query.get(), closed.get()):
                tree.insert("", "end", iid=str(r["account_no"]), values=(
                    r["account_no"], r["full_name"], r["age"], r["account_type"],
                    pounds(r["balance_pence"]), r["phone"], r["status"]))

        ttk.Button(search_bar, text="Search", command=refresh).pack(side="left")
        inp.bind("<Return>", lambda _e: refresh())
        self._buttons(panel, [("Create", self.new_account, "Accent.TButton"),
                              ("View details", lambda: self._with_account(tree, self.account_details), "TButton"),
                              ("Edit", lambda: self._with_account(tree, self.edit_account), "TButton"),
                              ("Close", lambda: self._with_account(tree, self.close_account), "Danger.TButton"),
                              ("Reopen", lambda: self._with_account(tree, self.reopen_account), "TButton")
                              ] if self.session.role == "admin" else
                      [("Create", self.new_account, "Accent.TButton"),
                       ("View details", lambda: self._with_account(tree, self.account_details), "TButton"),
                       ("Edit", lambda: self._with_account(tree, self.edit_account), "TButton"),
                       ("Close", lambda: self._with_account(tree, self.close_account), "Danger.TButton")])
        tree = self._tree(panel, [("number", "Account #", 95), ("name", "Name", 170),
                                  ("age", "Age", 60), ("type", "Type", 110),
                                  ("balance", "Balance", 150), ("phone", "Phone", 135),
                                  ("status", "Status", 85)])
        tree.bind("<Double-1>", lambda _e: self._with_account(tree, self.account_details))
        if self.session.role == "admin":
            ttk.Button(panel, text="Export visible accounts (CSV)", command=lambda: self._export_accounts(query.get(), closed.get())).pack(anchor="w", pady=(14, 0))
        refresh()

    def _with_account(self, tree: ttk.Treeview, fn: Callable[[int], None]) -> None:
        acct = self._selected(tree)
        if acct is not None:
            fn(acct)

    def new_account(self) -> None:
        assert self.session
        def save(v: dict[str, str]) -> None:
            num = self.db.create_account(self.session, v["name"], v["age"], v["address"],
                                         v["balance"], v["type"], v["phone"])
            messagebox.showinfo("Account created", f"New account number: {num}", parent=self.root)
            self.navigate("Accounts")
        FormDialog(self.root, "Create customer account", [
            ("name", "Full name", "", False), ("age", "Age", "", False),
            ("address", "Address", "", False), ("balance", "Opening deposit (£)", "0.00", False),
            ("type", "Account type", "Current", False), ("phone", "Mobile number", "", False)], save)

    def edit_account(self, account_no: int) -> None:
        assert self.session
        a = self._call(self.db.get_account, self.session, account_no)
        if not a:
            return
        def save(v: dict[str, str]) -> None:
            self.db.update_account(self.session, account_no, name=v["name"], age=v["age"],
                                   address=v["address"], account_type=v["type"], phone=v["phone"])
            self.navigate("Accounts")
        FormDialog(self.root, f"Edit account #{account_no}", [
            ("name", "Full name", a["full_name"], False), ("age", "Age", str(a["age"]), False),
            ("address", "Address", a["address"], False), ("type", "Account type", a["account_type"], False),
            ("phone", "Mobile number", a["phone"], False)], save,
            "Balance changes are recorded via deposits, withdrawals or transfers—not profile edits.")

    def close_account(self, account_no: int) -> None:
        assert self.session
        if messagebox.askyesno("Confirm closure", f"Close account #{account_no}? It must have a zero balance.\n\n"
                                "The account and ledger history are retained for audit.", parent=self.root):
            try:
                self.db.close_account(self.session, account_no)
            except (BankError, sqlite3.Error) as exc:
                messagebox.showerror("Unable to close account", str(exc), parent=self.root)
            else:
                self.navigate("Accounts")

    def reopen_account(self, account_no: int) -> None:
        assert self.session
        try:
            self.db.reopen_account(self.session, account_no)
        except (BankError, sqlite3.Error) as exc:
            messagebox.showerror("Unable to reopen account", str(exc), parent=self.root)
        else:
            self.navigate("Accounts")

    def account_details(self, account_no: int) -> None:
        assert self.session
        a = self._call(self.db.get_account, self.session, account_no)
        if not a:
            return
        w = tk.Toplevel(self.root)
        w.title(f"Account #{account_no}")
        w.geometry("780x570")
        w.configure(bg=PANEL)
        body = ttk.Frame(w, padding=23)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Account #{account_no} · {a['full_name']}", style="Title.TLabel").pack(anchor="w")
        data = [("Balance", pounds(a["balance_pence"])), ("Status", a["status"]),
                ("Age", str(a["age"])), ("Address", a["address"]),
                ("Type", a["account_type"]), ("Phone", a["phone"])]
        for label, value in data:
            ttk.Label(body, text=f"{label}:  {value}").pack(anchor="w", pady=4)
        ttk.Label(body, text="Recent ledger entries", style="Muted.TLabel").pack(anchor="w", pady=(16, 8))
        tree = self._tree(body, [("created", "UTC", 170), ("kind", "Kind", 155),
                                 ("amount", "Amount", 110), ("balance", "Balance", 120)])
        for row in self.db.transactions(self.session, account_no, limit=100):
            tree.insert("", "end", values=(row["created_at"][:19].replace("T", " "), row["kind"],
                                             pounds(row["amount_pence"]), pounds(row["balance_after_pence"])))

    def show_money(self) -> None:
        assert self.session
        panel = self._section()
        ttk.Label(panel, text="Deposit, withdraw or check a balance", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text="Account number").pack(anchor="w", pady=(10, 5))
        acct = tk.StringVar()
        ttk.Entry(panel, textvariable=acct, width=32).pack(anchor="w")
        ttk.Label(panel, text="Amount in GBP (e.g. 12.50)").pack(anchor="w", pady=(15, 5))
        amount = tk.StringVar()
        ttk.Entry(panel, textvariable=amount, width=32).pack(anchor="w")
        ttk.Label(panel, text="Optional transaction note").pack(anchor="w", pady=(15, 5))
        note = tk.StringVar()
        ttk.Entry(panel, textvariable=note, width=65).pack(anchor="w")
        status = ttk.Label(panel, text="", style="Muted.TLabel")
        status.pack(anchor="w", pady=(22, 0))

        def action(kind: str) -> None:
            try:
                account_no = int(acct.get())
                account = self.db.get_account(self.session, account_no)
                if kind == "Check":
                    status.configure(text=f"Account #{account_no} · {account['full_name']} · Balance {pounds(account['balance_pence'])}")
                    return
                if not messagebox.askyesno("Confirm transaction", f"{kind} £{amount.get()} on account #{account_no}\n"
                                           f"Customer: {account['full_name']}?", parent=self.root):
                    return
                fn = self.db.deposit if kind == "Deposit" else self.db.withdraw
                new_balance = fn(self.session, account_no, amount.get(), note.get())
                amount.set("")
                status.configure(text=f"{kind} completed. New balance: {pounds(new_balance)}")
            except (BankError, ValueError, sqlite3.Error) as exc:
                messagebox.showerror("Transaction rejected", str(exc), parent=self.root)

        self._buttons(panel, [("Check balance", lambda: action("Check"), "TButton"),
                              ("Deposit", lambda: action("Deposit"), "Accent.TButton"),
                              ("Withdraw", lambda: action("Withdraw"), "Danger.TButton")])
        ttk.Label(panel, text="Transactions are committed atomically with their audit and ledger records.",
                  style="Muted.TLabel").pack(anchor="w", pady=(20, 0))

    def show_transfers(self) -> None:
        assert self.session
        panel = self._section()
        ttk.Label(panel, text="Internal account transfer", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        values: dict[str, tk.StringVar] = {}
        for key, label in (("from", "From account number"), ("to", "To account number"),
                           ("amount", "Transfer amount (£)"), ("note", "Optional reference or note")):
            ttk.Label(panel, text=label).pack(anchor="w", pady=(12, 5))
            var = tk.StringVar()
            values[key] = var
            ttk.Entry(panel, textvariable=var, width=48).pack(anchor="w")

        def transfer() -> None:
            try:
                src = self.db.get_account(self.session, int(values["from"].get()))
                dst = self.db.get_account(self.session, int(values["to"].get()))
                if not messagebox.askyesno("Confirm transfer", f"Transfer £{values['amount'].get()}\n"
                                           f"From #{src['account_no']} · {src['full_name']}\n"
                                           f"To #{dst['account_no']} · {dst['full_name']}?", parent=self.root):
                    return
                ref = self.db.transfer(self.session, src["account_no"], dst["account_no"],
                                       values["amount"].get(), values["note"].get())
                messagebox.showinfo("Transfer completed", f"Transfer reference: {ref}", parent=self.root)
                values["amount"].set("")
            except (BankError, ValueError, sqlite3.Error) as exc:
                messagebox.showerror("Transfer rejected", str(exc), parent=self.root)

        ttk.Button(panel, text="Confirm internal transfer", style="Accent.TButton", command=transfer).pack(anchor="w", pady=(22, 0))

    def show_history(self) -> None:
        assert self.session
        panel = self._section()
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 14))
        ttk.Label(row, text="Account number (blank = all)").pack(side="left", padx=(0, 12))
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=20).pack(side="left", padx=(0, 9))
        tree: ttk.Treeview
        def refresh() -> None:
            acct = int(var.get()) if var.get().strip() else None
            records = self.db.transactions(self.session, acct)
            for iid in tree.get_children():
                tree.delete(iid)
            for r in records:
                tree.insert("", "end", values=(r["id"], r["created_at"][:19].replace("T", " "),
                                                 r["account_no"], r["kind"].replace("_", " "),
                                                 pounds(r["amount_pence"]), pounds(r["balance_after_pence"]),
                                                 r["counterparty"] or "", r["transfer_ref"] or "", r["note"]))
        ttk.Button(row, text="Filter", command=lambda: self._call(refresh)).pack(side="left")
        ttk.Button(row, text="Export displayed history (CSV)", command=lambda: self._export_history(var.get())).pack(side="left", padx=(8, 0))
        tree = self._tree(panel, [("id", "ID", 55), ("date", "UTC", 170), ("acct", "Account", 76),
                                  ("kind", "Operation", 135), ("amount", "Amount", 110),
                                  ("balance", "After", 110), ("peer", "Other account", 110),
                                  ("ref", "Transfer ref", 145), ("note", "Note", 180)])
        refresh()

    def _save_csv(self, suggested: str, cols: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title="Export CSV", defaultextension=".csv",
                                            initialfile=suggested, filetypes=[("CSV", "*.csv")])
        if path:
            try:
                export_csv(path, cols, rows)
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc), parent=self.root)
            else:
                messagebox.showinfo("Export complete", f"Saved {len(rows)} rows.\nKeep exported personal data secure.", parent=self.root)

    def _export_accounts(self, search: str, include_closed: bool) -> None:
        assert self.session
        rows = self.db.list_accounts(self.session, search, include_closed)
        self._save_csv("accounts.csv", [("account_no", "Account number"), ("full_name", "Name"),
                                         ("age", "Age"), ("address", "Address"),
                                         ("balance_gbp", "Balance GBP"), ("account_type", "Account type"),
                                         ("phone", "Phone"), ("status", "Status")],
                       [{**r, "balance_gbp": f"{r['balance_pence']//100}.{r['balance_pence']%100:02d}"} for r in rows])

    def _export_history(self, account: str) -> None:
        assert self.session
        try:
            rows = self.db.transactions(self.session, int(account) if account.strip() else None, 2000)
        except (BankError, ValueError) as exc:
            messagebox.showerror("Invalid filter", str(exc), parent=self.root)
            return
        rows = [{**r, "amount_gbp": f"{r['amount_pence']//100}.{r['amount_pence']%100:02d}",
                 "balance_gbp": f"{r['balance_after_pence']//100}.{r['balance_after_pence']%100:02d}"} for r in rows]
        self._save_csv("transaction_history.csv", [("id", "ID"), ("created_at", "UTC time"),
                      ("account_no", "Account"), ("kind", "Kind"), ("amount_gbp", "Amount GBP"),
                      ("balance_gbp", "Balance after GBP"), ("counterparty", "Counterparty"),
                      ("transfer_ref", "Transfer ref"), ("note", "Note"), ("actor", "Staff")], rows)

    def show_employees(self) -> None:
        assert self.session
        panel = self._section()
        tree: ttk.Treeview
        def refresh() -> None:
            for iid in tree.get_children():
                tree.delete(iid)
            for r in self.db.list_employees(self.session):
                tree.insert("", "end", iid=str(r["id"]), values=(r["id"], r["username"],
                       r["position"], pounds(r["salary_pence"]), "Enabled" if r["active"] else "Disabled",
                       "Yes" if r["must_change"] else "No"))
        self._buttons(panel, [("Create employee", self.new_employee, "Accent.TButton"),
                              ("Edit employee", lambda: self._with_account(tree, self.edit_employee), "TButton"),
                              ("Reset password", lambda: self._with_account(tree, self.reset_employee_password), "TButton")])
        tree = self._tree(panel, [("id", "ID", 60), ("name", "Username", 175),
                                  ("position", "Position", 180), ("salary", "Salary (GBP)", 135),
                                  ("active", "Status", 110), ("rotation", "Must change password", 155)])
        refresh()
        ttk.Label(panel, text="Passwords are never displayed. Employee password resets require a new temporary passphrase.",
                  style="Muted.TLabel").pack(anchor="w", pady=(13, 0))

    def new_employee(self) -> None:
        assert self.session
        def save(v: dict[str, str]) -> None:
            self.db.create_employee(self.session, v["username"], v["password"], v["salary"], v["position"])
            self.navigate("Employees")
        FormDialog(self.root, "Create employee", [
            ("username", "Login username", "", False),
            ("password", "Temporary password (12+ characters)", "", True),
            ("salary", "Salary in GBP", "0.00", False), ("position", "Position", "Cashier", False)], save,
            "The employee must change this temporary password on their first login.")

    def edit_employee(self, user_id: int) -> None:
        assert self.session
        r = next((row for row in self.db.list_employees(self.session) if row["id"] == user_id), None)
        if not r:
            messagebox.showerror("Missing employee", "Employee not found.", parent=self.root)
            return
        def save(v: dict[str, str]) -> None:
            enabled = v["active"].strip().lower()
            if enabled not in ("yes", "no"):
                raise BankError("Enabled must be 'yes' or 'no'.")
            self.db.update_employee(self.session, user_id, username=v["username"], salary=v["salary"],
                                    position=v["position"], active=enabled == "yes")
            self.navigate("Employees")
        FormDialog(self.root, f"Edit employee #{user_id}", [
            ("username", "Username", r["username"], False),
            ("salary", "Salary (GBP)", f"{r['salary_pence']//100}.{r['salary_pence']%100:02d}", False),
            ("position", "Position", r["position"], False),
            ("active", "Account enabled? (yes/no)", "yes" if r["active"] else "no", False)], save,
            "Set enabled to 'no' to deactivate without destroying transaction or audit history.")

    def reset_employee_password(self, user_id: int) -> None:
        assert self.session
        def save(v: dict[str, str]) -> None:
            if v["password"] != v["confirm"]:
                raise BankError("Passwords do not match.")
            self.db.reset_employee_password(self.session, user_id, v["password"])
            messagebox.showinfo("Reset complete", "Password reset. Employee must change it at next login.", parent=self.root)
            self.navigate("Employees")
        FormDialog(self.root, f"Reset employee #{user_id} password", [
            ("password", "New temporary password (12+ characters)", "", True),
            ("confirm", "Confirm password", "", True)], save)

    def show_audit(self) -> None:
        assert self.session
        panel = self._section()
        ttk.Label(panel, text="Recent administrator and staff actions", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        tree = self._tree(panel, [("id", "ID", 55), ("date", "UTC", 195),
                                  ("staff", "Performed by", 120), ("event", "Event", 220),
                                  ("target", "Target", 160), ("details", "Details", 290)])
        for r in self.db.audit_log(self.session):
            tree.insert("", "end", values=(r["id"], r["created_at"][:19].replace("T", " "),
                                             r["actor"], r["event"], r["target"], r["details"]))

    def show_settings(self) -> None:
        assert self.session
        panel = self._section()
        ttk.Label(panel, text="Account and local database settings", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        ttk.Label(panel, text=f"Signed in as {self.session.username} ({self.session.role})").pack(anchor="w", pady=5)
        ttk.Label(panel, text=f"Database: {self.db.path}", style="Muted.TLabel", wraplength=750).pack(anchor="w", pady=5)
        ttk.Button(panel, text="Change my password", command=self.show_password_change).pack(anchor="w", pady=(15, 10))
        if self.session.role == "admin":
            ttk.Button(panel, text="Backup SQLite database", style="Accent.TButton", command=self.backup).pack(anchor="w", pady=5)
            ttk.Label(panel, text="Backups and CSV exports contain private data; store them securely.\n"
                      "This application is an offline educational project, not a regulated banking platform.",
                      style="Muted.TLabel").pack(anchor="w", pady=(16, 0))

    def backup(self) -> None:
        assert self.session
        target = filedialog.asksaveasfilename(parent=self.root, title="Create database backup", defaultextension=".db",
                    initialfile="bankmanaging-backup.db", filetypes=[("SQLite database", "*.db")])
        if not target:
            return
        saved = self._call(self.db.backup_database, self.session, target)
        if saved:
            messagebox.showinfo("Backup complete", f"Saved backup to:\n{saved}", parent=self.root)

    def exit(self) -> None:
        self.db.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Bank Manager (educational)")
    parser.add_argument("--db", type=Path, default=None, help="SQLite database path (default: next to backend.py)")
    args = parser.parse_args()
    try:
        db = BankDB(args.db) if args.db else BankDB()
    except (BankError, sqlite3.Error, OSError) as exc:
        # Tk's messagebox creates a small temporary root when needed.
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Database unavailable", str(exc), parent=root)
        root.destroy()
        raise SystemExit(1) from exc
    BankApp(db).run()


if __name__ == "__main__":
    main()
