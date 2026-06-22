#!/usr/bin/env python3
"""
Script Name     : xkcd_downloader.py
Description     : Downloads XKCD comics using the official JSON API.
                  Supports downloading the latest comic, a random comic,
                  or a specific comic by number. Saves alt text/title metadata
                  alongside the image.
"""

import os
import sys
import json
import random
import requests

API_LATEST = "https://xkcd.com/info.0.json"
API_SPECIFIC = "https://xkcd.com/{num}/info.0.json"


def fetch_comic_data(url):
    """Fetches JSON data from the XKCD API."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[-] Network error fetching comic data: {e}")
        sys.exit(1)


def download_file(url, save_path):
    """Downloads a file from a URL and saves it to a path."""
    try:
        response = requests.get(url, stream=True, timeout=20)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except requests.exceptions.RequestException as e:
        print(f"[-] Network error downloading comic image: {e}")
        sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download XKCD comics with metadata.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--latest', action='store_true', help='Download the latest comic (default).')
    group.add_argument('--random', action='store_true', help='Download a random comic.')
    group.add_argument('--comic', type=int, metavar='NUM', help='Download a specific comic number.')
    parser.add_argument('--dir', type=str, default='comics', help='Directory to save the comic (default: comics).')
    
    args = parser.parse_args()

    # Create destination directory
    save_dir = os.path.abspath(args.dir)
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir)
        except OSError as e:
            print(f"[-] Error creating directory '{save_dir}': {e}")
            sys.exit(1)

    print(f"[*] Fetching latest comic details to find boundaries...")
    latest_data = fetch_comic_data(API_LATEST)
    max_num = latest_data['num']

    # Select target comic URL
    if args.random:
        target_num = random.randint(1, max_num)
        print(f"[*] Selecting random comic #{target_num} of {max_num}...")
        comic_url = API_SPECIFIC.format(num=target_num)
        comic_data = fetch_comic_data(comic_url)
    elif args.comic:
        target_num = args.comic
        if target_num < 1 or target_num > max_num:
            print(f"[-] Error: Comic number must be between 1 and {max_num}.")
            sys.exit(1)
        print(f"[*] Fetching comic #{target_num}...")
        comic_url = API_SPECIFIC.format(num=target_num)
        comic_data = fetch_comic_data(comic_url)
    else:
        # Default to latest
        print(f"[*] Fetching latest comic #{max_num}...")
        comic_data = latest_data

    # Parse details
    num = comic_data['num']
    title = comic_data['title']
    alt_text = comic_data['alt']
    image_url = comic_data['img']
    
    # Extract extension from URL
    img_ext = os.path.splitext(image_url)[1] or '.png'
    
    # Safe filenames
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    img_filename = f"{num}_{safe_title}{img_ext}"
    meta_filename = f"{num}_{safe_title}_metadata.json"
    
    img_save_path = os.path.join(save_dir, img_filename)
    meta_save_path = os.path.join(save_dir, meta_filename)

    print(f"[*] Title: {title}")
    print(f"[*] Alt text: {alt_text}")
    print(f"[*] Downloading image from: {image_url} ...")
    
    download_file(image_url, img_save_path)
    print(f"[+] Saved image to: {img_save_path}")

    # Save metadata
    try:
        with open(meta_save_path, 'w', encoding='utf-8') as f:
            json.dump(comic_data, f, indent=4)
        print(f"[+] Saved metadata to: {meta_save_path}")
    except OSError as e:
        print(f"[-] Error saving metadata file: {e}")

    print("[+] Done!")


if __name__ == "__main__":
    main()
