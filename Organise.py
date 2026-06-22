#!/usr/bin/python3
"""
Script Name     : Organise.py
Description     : Organises files in a directory into folders by type (e.g. Video, Images, etc.).
"""
import sys
import shutil
from pathlib import Path

EXT_VIDEO_LIST = ['FLV', 'WMV', 'MOV', 'MP4', 'MPEG', '3GP', 'MKV', 'AVI']
EXT_IMAGE_LIST = ['JPG', 'JPEG', 'GIF', 'PNG', 'SVG']
EXT_DOCUMENT_LIST = ['DOC', 'DOCX', 'PPT', 'PPTX', 'PAGES', 'PDF', 'ODT', 'ODP', 'XLSX', 'XLS', 'ODS', 'TXT', 'IN', 'OUT', 'MD']
EXT_MUSIC_LIST = ['MP3', 'WAV', 'WMA', 'MKA', 'AAC', 'MID', 'RA', 'RAM', 'RM', 'OGG']
EXT_CODE_LIST = ['CPP', 'RB', 'PY', 'HTML', 'CSS', 'JS']
EXT_EXECUTABLE_LIST = ['LNK', 'DEB', 'EXE', 'SH', 'BUNDLE']
EXT_COMPRESSED_LIST = ['RAR', 'JAR', 'ZIP', 'TAR', 'MAR', 'ISO', 'LZ', '7ZIP', 'TGZ', 'GZ', 'BZ2']

TYPES_LIST = ['Video', 'Images', 'Documents', 'Music', 'Codes', 'Executables', 'Compressed']
EXTENSIONS_MAPS = [
    EXT_VIDEO_LIST, EXT_IMAGE_LIST, EXT_DOCUMENT_LIST,
    EXT_MUSIC_LIST, EXT_CODE_LIST, EXT_EXECUTABLE_LIST,
    EXT_COMPRESSED_LIST
]


def get_destination_directory():
    # Retrieve directory from command line arguments or prompt user
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1])
        if target_dir.is_dir():
            return target_dir
        else:
            print(f"Error: Command line argument '{sys.argv[1]}' is not a valid directory.")

    while True:
        user_input = input('Enter the Path of directory to organize (or "quit" to exit): ').strip()
        if user_input.lower() == 'quit':
            sys.exit(0)
        target_dir = Path(user_input)
        if target_dir.is_dir():
            return target_dir
        print('Error! Invalid directory path. Please try again.')


def organize_directory(dest_path):
    print(f"Organizing files in: {dest_path.resolve()}")
    
    # Iterate through all files in the directory
    for item in dest_path.iterdir():
        if item.is_file():
            file_ext = item.suffix.lstrip('.').upper()
            
            # Find matching category
            matched_category = None
            for name, ext_list in zip(TYPES_LIST, EXTENSIONS_MAPS):
                if file_ext in ext_list:
                    matched_category = name
                    break
            
            if matched_category:
                category_dir = dest_path / matched_category
                try:
                    category_dir.mkdir(exist_ok=True)
                except OSError as e:
                    print(f"Error creating directory {category_dir}: {e}")
                    continue
                
                dest_file = category_dir / item.name
                try:
                    shutil.move(str(item), str(dest_file))
                    print(f"Moved: {item.name} -> {matched_category}/")
                except OSError as e:
                    print(f"Error moving {item.name}: {e}")


def main():
    dest_path = get_destination_directory()
    organize_directory(dest_path)
    print('Done Arranging Files in your specified directory!')


if __name__ == '__main__':
    main()
