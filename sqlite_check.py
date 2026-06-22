#!/usr/bin/env python3
"""
Script Name     : sqlite_check.py
Description     : Performs diagnostic checks on a SQLite database. Prints database details,
                  tables, column structures, and row counts.
"""

import os
import sys
import argparse
import sqlite3


def create_demo_db(db_path):
    """Generates a demo SQLite database with mock tables and data for verification."""
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            # Create mock user table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    email TEXT NOT NULL
                )
            ''')
            # Create mock task table
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            ''')
            # Insert mock values
            cur.execute("INSERT INTO users (username, email) VALUES ('admin', 'admin@local.host')")
            cur.execute("INSERT INTO users (username, email) VALUES ('user1', 'user1@local.host')")
            cur.execute("INSERT INTO tasks (title, status) VALUES ('Review code', 'completed')")
            cur.execute("INSERT INTO tasks (title, status) VALUES ('Fix sqlite_check bugs', 'in_progress')")
            conn.commit()
        print(f"[+] Demo database '{db_path}' created successfully!")
    except sqlite3.Error as e:
        print(f"[-] Error creating demo database: {e}")


def get_db_diagnostics(db_path):
    """Diagnoses a SQLite database and displays diagnostics in a clean format."""
    # Check if database file exists
    if not os.path.exists(db_path):
        print(f"[-] Database file '{db_path}' does not exist.")
        
        # If default demo db is missing, generate it
        if os.path.basename(db_path) == "demo_jarvis.db":
            print("[*] Generating a mock database 'demo_jarvis.db' to run diagnostics...")
            create_demo_db(db_path)
        else:
            sys.exit(1)

    print(f"\n[*] Running diagnostics on database: {os.path.abspath(db_path)}")
    try:
        print(f"[*] Database file size: {os.path.getsize(db_path) / 1024:.2f} KB")
    except OSError as e:
        print(f"[-] Error reading file size: {e}")

    try:
        # Use context manager to prevent connection resource leaks
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            
            # Query version
            cur.execute('SELECT SQLITE_VERSION()')
            version = cur.fetchone()[0]
            print(f"[*] SQLite Version: {version}")
            
            # Query table names
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            
            if not tables:
                print("[-] Database contains no tables.")
                return
                
            print(f"[+] Found {len(tables)} tables:")
            print("=" * 60)
            
            for table in tables:
                # Query row count
                cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                row_count = cur.fetchone()[0]
                
                # Query table columns and types
                cur.execute(f"PRAGMA table_info(`{table}`)")
                columns = cur.fetchall()
                col_details = [f"{col[1]} ({col[2]})" for col in columns]
                
                print(f"Table Name : {table}")
                print(f"Row Count  : {row_count}")
                print(f"Columns    : {', '.join(col_details)}")
                print("-" * 60)
                
    except sqlite3.Error as e:
        print(f"[-] SQLite Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SQLite database diagnostic tool.")
    parser.add_argument('db_path', nargs='?', default=None, help='Path to SQLite database file. If omitted, checks environment variables or uses a demo db.')
    args = parser.parse_args()

    db_path = args.db_path

    if not db_path:
        # Check environment variable
        dropbox = os.getenv("dropbox")
        if dropbox:
            # Replaced manual slash joins with safe path.join
            db_path = os.path.join(dropbox, "Databases", "jarvis.db")
        else:
            # Fallback to local Databases/jarvis.db
            local_path = os.path.join("Databases", "jarvis.db")
            if os.path.exists(local_path):
                db_path = local_path
            else:
                db_path = "demo_jarvis.db"

    get_db_diagnostics(db_path)


if __name__ == '__main__':
    main()
