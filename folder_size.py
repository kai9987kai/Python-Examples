# Script Name   : folder_size.py
# Author        : Craig Richards / Improved
# Description   : Scans a directory and all subdirectories, displaying the size
#                 in a human-readable format. Supports detailed breakdown.

import os
import sys
import argparse


def format_size(size_bytes):
    """Formats a size in bytes to the most appropriate human-readable unit."""
    for unit in ['Bytes', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_folder_size(directory):
    """Recursively computes total directory size, ignoring symlinks and handling errors."""
    total_size = 0
    for root, dirs, files in os.walk(directory):
        for f in files:
            fp = os.path.join(root, f)
            try:
                # Ignore symlinks to avoid duplicate counts or cycles
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
            except OSError:
                # Safely skip files with permission errors or that were deleted during scan
                continue
    return total_size


def print_breakdown(directory):
    """Prints size breakdown of top-level files and folders inside the directory."""
    try:
        items = os.listdir(directory)
    except OSError as e:
        print(f"[-] Error listing directory: {e}")
        return

    breakdown = []
    print(f"\n[*] Breakdown of '{directory}':")
    print("-" * 60)
    
    for item in items:
        item_path = os.path.join(directory, item)
        if os.path.islink(item_path):
            continue
            
        if os.path.isdir(item_path):
            size = get_folder_size(item_path)
            name = item + "/"
        else:
            try:
                size = os.path.getsize(item_path)
            except OSError:
                size = 0
            name = item
            
        breakdown.append((name, size))
        
    # Sort by size descending
    breakdown.sort(key=lambda x: x[1], reverse=True)
    
    for name, size in breakdown:
        print(f"  {format_size(size):<18} | {name}")
    print("-" * 60)


def main():
    parser = argparse.ArgumentParser(description="Calculate sizes of directories and files.")
    parser.add_argument('directory', nargs='?', default='.', help='Target directory to scan (default: current directory).')
    parser.add_argument('-b', '--breakdown', action='store_true', help='Show sorted size breakdown of top-level items.')
    args = parser.parse_args()

    target_dir = os.path.abspath(args.directory)
    if not os.path.exists(target_dir):
        print(f"[-] Error: Path '{target_dir}' does not exist.")
        sys.exit(1)
        
    if not os.path.isdir(target_dir):
        # If it is a file, print its file size directly
        try:
            size = os.path.getsize(target_dir)
            print(f"File Size: {format_size(size)}")
        except OSError as e:
            print(f"[-] Error getting file size: {e}")
        return

    print(f"[*] Scanning directory: {target_dir}")
    total_size = get_folder_size(target_dir)
    
    if total_size == 0:
        print("Folder is empty or contains no readable files.")
    else:
        print(f"Total Folder Size: {format_size(total_size)}")
        
    if args.breakdown:
        print_breakdown(target_dir)


if __name__ == '__main__':
    main()
