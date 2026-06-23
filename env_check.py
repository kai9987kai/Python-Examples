# Script Name   : env_check.py
# Author        : Craig Richards / Improved
# Description   : Checks if specified environment variables are set and displays their settings.

import os
import sys


def create_default_conf(conf_path):
    """Creates a default template env_check.conf with common environment variables."""
    print(f"[*] Creating default configuration file at: {conf_path}")
    # Selection of common environment variables across Windows and Unix/Linux
    common_vars = ["PATH", "TEMP", "USERNAME", "OS", "HOMEPATH", "COMPUTERNAME"]
    try:
        with open(conf_path, 'w', encoding='utf-8') as f:
            for var in common_vars:
                f.write(f"{var}\n")
    except OSError as e:
        print(f"[-] Error writing configuration template: {e}")


def main():
    confdir = os.getenv("my_config")
    if not confdir:
        # Fallback to current directory if env variable is not set
        confdir = "."
        
    conffile = 'env_check.conf'
    conffilename = os.path.join(confdir, conffile)

    # Automatically generate configuration if missing
    if not os.path.exists(conffilename):
        create_default_conf(conffilename)

    if not os.path.exists(conffilename):
        print(f"[-] Error: Configuration file '{conffilename}' not found.")
        sys.exit(1)

    print(f"[*] Reading environment checks from: {conffilename}\n")
    
    try:
        # Use context manager to prevent file locks
        with open(conffilename, 'r', encoding='utf-8') as f:
            variables = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except OSError as e:
        print(f"[-] Error reading configuration file: {e}")
        sys.exit(1)

    for env_check in variables:
        print(f'[{env_check}]')
        newenv = os.getenv(env_check)

        if newenv is None:
            print(f"  [-] {env_check} is NOT set\n")
        else:
            print(f"  [+] Current Setting: {newenv}\n")


if __name__ == '__main__':
    main()
