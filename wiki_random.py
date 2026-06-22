#!/usr/bin/env python3
"""
Script Name     : wiki_random.py
Description     : Fetches random Wikipedia articles and prompts the user to open them.
"""

import sys
import webbrowser
import requests

PAGE_COUNT = 10
API_URL = f"https://en.wikipedia.org/w/api.php?action=query&list=random&rnnamespace=0&rnlimit={PAGE_COUNT}&format=json"


def load_random_pages():
    """Main loop to fetch and prompt user to browse random Wikipedia articles."""
    while True:
        try:
            response = requests.get(API_URL, timeout=10)
            response.raise_for_status()
            json_data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"[-] Network error fetching Wikipedia details: {e}")
            break

        # Check if the expected JSON path exists
        if 'query' not in json_data or 'random' not in json_data['query']:
            print("[-] Error: Unexpected response format from Wikipedia API.")
            break

        articles = json_data['query']['random']
        print(f"\n[+] {PAGE_COUNT} randomly generated Wikipedia pages:")
        print("-" * 50)
        for idx, article in enumerate(articles):
            print(f"  {idx}: {article['title']}")
        print("-" * 50)

        # Inner loop for user choice until they select a valid index, retry, or exit
        while True:
            choice = input("\nEnter index (0-9) to read, 'r' to load new list, 'n' to exit: ").strip().lower()
            
            if choice == 'r':
                print("[*] Loading new random pages...")
                break  # Break inner loop to fetch new list in outer loop
            elif choice == 'n':
                print("[*] Goodbye!")
                return
            else:
                try:
                    idx = int(choice)
                    if 0 <= idx < len(articles):
                        article_id = articles[idx]['id']
                        article_title = articles[idx]['title']
                        print(f"[*] Opening '{article_title}' in browser...")
                        
                        web_url = f"https://en.wikipedia.org/wiki?curid={article_id}"
                        webbrowser.open(web_url)
                    else:
                        print(f"[-] Invalid range. Please enter an integer between 0 and {len(articles) - 1}.")
                except ValueError:
                    print("[-] Invalid input. Please enter a valid index number, 'r', or 'n'.")


if __name__ == '__main__':
    print("=========================================")
    print("       WIKIPEDIA RANDOM EXPLORER         ")
    print("=========================================")
    load_random_pages()
