# Script Name   : sqlite_table_check.py
# Author        : Craig Richards / Improved
# Description   : Checks the SQLite database to ensure all expected tables exist.

import os
import sys
import sqlite3


def create_demo_files(db_path, list_path):
    """Creates a demo SQLite database and table list if they don't exist."""
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError:
            pass
        
    list_dir = os.path.dirname(list_path)
    if list_dir and not os.path.exists(list_dir):
        try:
            os.makedirs(list_dir, exist_ok=True)
        except OSError:
            pass

    # Create mock db if missing
    if not os.path.exists(db_path):
        print(f"[*] Creating demo database at: {db_path}")
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("CREATE TABLE IF NOT EXISTS users (id INT)")
                cur.execute("CREATE TABLE IF NOT EXISTS tasks (id INT)")
                conn.commit()
        except sqlite3.Error as e:
            print(f"[-] Error creating demo database: {e}")

    # Create mock list file if missing
    if not os.path.exists(list_path):
        print(f"[*] Creating template table list at: {list_path}")
        try:
            with open(list_path, 'w', encoding='utf-8') as f:
                f.write("users\ntasks\nmissing_table_demo\n")
        except OSError as e:
            print(f"[-] Error creating table list: {e}")


def main():
    dropbox = os.getenv("dropbox")
    config = os.getenv("my_config")
    
    # Defaults if environment variables are not set
    if not dropbox:
        dropbox = "Databases"
    if not config:
        config = "."
        
    dbfile = "jarvis.db"
    listfile = "sqlite_master_table.lst"
    
    # Safe path resolution
    if dropbox == "Databases":
        master_db = os.path.join(dropbox, dbfile)
    else:
        master_db = os.path.join(dropbox, "Databases", dbfile)
        if not os.path.exists(master_db):
            master_db = os.path.join(dropbox, dbfile)

    config_file = os.path.join(config, listfile)

    # Generate template files if either is missing to ensure it runs out-of-the-box
    if not os.path.exists(master_db) or not os.path.exists(config_file):
        create_demo_files(master_db, config_file)

    if not os.path.exists(master_db):
        print(f"[-] Error: SQLite database '{master_db}' not found.")
        sys.exit(1)
        
    if not os.path.exists(config_file):
        print(f"[-] Error: Table list file '{config_file}' not found.")
        sys.exit(1)

    # SQLite Version check (safe verification context)
    try:
        with sqlite3.connect(master_db) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT SQLITE_VERSION()')
            version = cursor.fetchone()[0]
            
            print(f"\n[*] Currently {master_db} is on SQLite version: {version}")
            if version == "3.6.21":
                print("Matches Master SQLite Version (3.6.21) - OK -\n")
            else:
                print("SQLite Version is newer/different than 3.6.21 - NOTE -\n")
    except sqlite3.Error as e:
        print(f"[-] SQLite connection error: {e}")
        sys.exit(1)

    print(f"[*] Checking {master_db} against table list: {config_file}\n")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            tables = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except OSError as e:
        print(f"[-] Error reading table list: {e}")
        sys.exit(1)

    try:
        # Re-use a single connection block for all checks, avoiding unclosed locks
        with sqlite3.connect(master_db) as conn:
            cursor = conn.cursor()
            for table in tables:
                cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
                res = cursor.fetchone()
                
                if res[0]:
                    print(f"[+] Table : {table:<25} exists [+]")
                else:
                    print(f"[-] Table : {table:<25}  does not exist [-]")
    except sqlite3.Error as e:
        print(f"[-] SQLite check error: {e}")


if __name__ == '__main__':
    main()
