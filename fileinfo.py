# Script Name       : fileinfo.py
# Author            : Unknown / Improved
# Created           : 28th November 2011
# Modified          : June 2026
# Description       : Shows file information for a given file or directory.

import os
import sys
import stat
import time

try_count = 5  # Allow 5 attempts (matches original bitwise shift limit)

while try_count > 0:
    file_name = input("Enter a file name: ").strip()
    
    if not os.path.exists(file_name):
        print(f"\nError: [{file_name}] No such file or directory\n")
        try_count -= 1
        continue

    try:
        file_stats = os.stat(file_name)
        
        # Safely compute lines and characters only if it's a file
        if os.path.isdir(file_name):
            count = 0
            t_char = 0
        else:
            # Use 'with open' context manager to close file and errors='ignore' for binary files
            with open(file_name, 'r', encoding='utf-8', errors='ignore') as fhand:
                content = fhand.read()
            t_char = len(content)
            count = len(content.splitlines())
            
        break
    except OSError as e:
        print(f"\nOSError: {e}\n")
        try_count -= 1

if try_count == 0:
    print("Trial limit exceeded \nExiting program")
    sys.exit()

# create a dictionary to hold file info
file_info = {
    'fname': file_name,
    'fsize': file_stats[stat.ST_SIZE],
    'f_lm': time.strftime("%d/%m/%Y %I:%M:%S %p", time.localtime(file_stats[stat.ST_MTIME])),
    'f_la': time.strftime("%d/%m/%Y %I:%M:%S %p", time.localtime(file_stats[stat.ST_ATIME])),
    'f_ct': time.strftime("%d/%m/%Y %I:%M:%S %p", time.localtime(file_stats[stat.ST_CTIME])),
    'no_of_lines': count,
    't_char': t_char
}

print("\nfile name =", file_info['fname'])
print("file size =", file_info['fsize'], "bytes")
print("last modified =", file_info['f_lm'])
print("last accessed =", file_info['f_la'])
print("creation time =", file_info['f_ct'])

if os.path.isdir(file_name):
    print("This is a directory")
else:
    print("This is not a directory\n")
    print(f"Total number of lines are = {file_info['no_of_lines']}")
    print(f"Total number of characters are = {file_info['t_char']}")
    print(f"\nA closer look at the os.stat({file_name}) tuple:")
    print(file_stats)
    print("\nThe above tuple has the following sequence:")
    print("""st_mode (protection bits), st_ino (inode number), 
    st_dev (device),    st_nlink (number of hard links),    
    st_uid (user ID of owner),   st_gid (group ID of owner),    
    st_size (file size, bytes),  st_atime (last access time, seconds since epoch),  
    st_mtime (last modification time),   st_ctime (time of creation, Windows)""")
