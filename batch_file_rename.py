# batch_file_rename.py
# Created: 6th August 2012
# Modified: June 2026

"""
This will batch rename a group of files in a given directory,
once you pass the current and new extensions.
"""

__author__ = 'Craig Richards'
__version__ = '2.0'

import os
import argparse
import sys


def batch_rename(work_dir, old_ext, new_ext, dry_run=False, case_insensitive=False):
    """
    This will batch rename a group of files in a given directory,
    once you pass the current and new extensions.
    """
    if not os.path.isdir(work_dir):
        print(f"[-] Error: Directory '{work_dir}' does not exist or is not a directory.")
        sys.exit(1)

    # Ensure extensions start with '.'
    if not old_ext.startswith('.'):
        old_ext = '.' + old_ext
    if not new_ext.startswith('.'):
        new_ext = '.' + new_ext

    print(f"[*] Scanning '{work_dir}' for files ending in '{old_ext}'...")
    
    rename_count = 0
    skipped_count = 0
    
    try:
        filenames = os.listdir(work_dir)
    except OSError as e:
        print(f"[-] Error reading directory contents: {e}")
        sys.exit(1)

    for filename in filenames:
        filepath = os.path.join(work_dir, filename)
        
        # Process files only
        if not os.path.isfile(filepath):
            continue
            
        split_file = os.path.splitext(filename)
        file_ext = split_file[1]
        
        # Check matching extension
        is_match = (file_ext.lower() == old_ext.lower()) if case_insensitive else (file_ext == old_ext)
        
        if is_match:
            new_filename = split_file[0] + new_ext
            new_filepath = os.path.join(work_dir, new_filename)
            
            # Check if destination file already exists (to avoid accidental overrides)
            if os.path.exists(new_filepath) and new_filename != filename:
                print(f"[!] Warning: Cannot rename '{filename}' to '{new_filename}' (target file already exists). Skipping.")
                skipped_count += 1
                continue
                
            if dry_run:
                print(f"[DRY RUN] Would rename: '{filename}' -> '{new_filename}'")
            else:
                try:
                    os.rename(filepath, new_filepath)
                    print(f"[+] Renamed: '{filename}' -> '{new_filename}'")
                except OSError as e:
                    print(f"[-] Error renaming '{filename}': {e}")
                    skipped_count += 1
                    continue
            
            rename_count += 1

    if dry_run:
        print(f"[*] Dry run finished. Would rename {rename_count} files (skipped {skipped_count}).")
    else:
        print(f"[*] Renaming finished. Successfully renamed {rename_count} files (skipped {skipped_count}).")


def get_parser():
    parser = argparse.ArgumentParser(description='Change file extensions in a working directory.')
    parser.add_argument('work_dir', type=str, help='The directory where extension changes occur.')
    parser.add_argument('old_ext', type=str, help='Old extension to look for (e.g. .txt or txt).')
    parser.add_argument('new_ext', type=str, help='New extension to apply (e.g. .md or md).')
    parser.add_argument('-d', '--dry-run', action='store_true', help='Preview changes without modifying files.')
    parser.add_argument('-i', '--case-insensitive', action='store_true', help='Enable case-insensitive extension matching.')
    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()
    batch_rename(args.work_dir, args.old_ext, args.new_ext, dry_run=args.dry_run, case_insensitive=args.case_insensitive)


if __name__ == '__main__':
    main()
