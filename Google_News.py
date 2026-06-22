#!/usr/bin/env python3
"""
Script Name     : Google_News.py
Description     : Fetches and displays news headlines from Google News RSS feeds
                  using only Python's standard library (no BS4 or lxml required!).
"""

import ssl
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET


def fetch_news(rss_url):
    """Fetches, parses, and prints headlines from a Google News RSS URL."""
    print(f"[*] Querying feed: {rss_url}")
    
    try:
        context = ssl._create_unverified_context()
    except AttributeError:
        context = None

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        req = urllib.request.Request(rss_url, headers=headers)
        
        if context:
            with urllib.request.urlopen(req, context=context, timeout=10) as response:
                xml_data = response.read()
        else:
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
    except urllib.error.URLError as e:
        print(f"[-] Network error querying feed: {e.reason}")
        return
    except Exception as e:
        print(f"[-] Unexpected error: {e}")
        return

    try:
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        if not items:
            print("[-] No news items found in this feed.")
            return

        print(f"[+] Found {len(items)} news headlines:")
        print("=" * 60)
        
        for item in items:
            title = item.find('title')
            link = item.find('link')
            pub_date = item.find('pubDate')
            
            title_text = title.text if title is not None else "No Title"
            link_text = link.text if link is not None else "No Link"
            date_text = pub_date.text if pub_date is not None else "Unknown Date"
            
            print(f"News Title  : {title_text}")
            print(f"News Link   : {link_text}")
            print(f"News Date   : {date_text}")
            print("+-" * 30)
            
        print("\n")
        
    except ET.ParseError as e:
        print(f"[-] XML parsing error: {e}")
    except Exception as e:
        print(f"[-] Error displaying news: {e}")


def main():
    # Modern Google News RSS URLs
    news_url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    sports_url = "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en"
    
    print("Fetching Google News headlines...")
    fetch_news(news_url)
    
    print("Fetching Google News Sports headlines...")
    fetch_news(sports_url)


if __name__ == "__main__":
    main()
