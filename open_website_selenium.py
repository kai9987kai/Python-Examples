#!/usr/bin/python3
"""
Description : Test internet connectivity and open a website using Selenium.
"""
import sys
import os
import urllib.request
import urllib.error

# Try importing selenium; warn if not installed
try:
    from selenium import webdriver
except ImportError:
    print("Warning: The 'selenium' library is required to run this script.")
    print("You can install it using: pip install selenium")
    print("You also need the geckodriver or appropriate webdriver for your browser.")
    sys.exit(1)

print("Testing Internet Connection...")
try:
    # Test if connection is up and running
    urllib.request.urlopen("http://google.com", timeout=2)
    print("Internet is working fine!\n")
    
    question = input("Do you want to open a website? (Y/N): ").strip().upper()
    if question == 'Y':
        search = input("Input website to open (e.g. http://google.com): ").strip()
        if not search.startswith("http://") and not search.startswith("https://"):
            search = "http://" + search
    else:
        sys.exit(0)

except urllib.error.URLError:
    print("No internet connection!")
    sys.exit(1)

print(f"Launching browser to open {search}...")
try:
    # Using Firefox webdriver (requires geckodriver)
    # Falling back to Chrome or Edge if Firefox isn't configured
    try:
        browser = webdriver.Firefox()
    except Exception:
        try:
            browser = webdriver.Chrome()
        except Exception:
            browser = webdriver.Edge()

    browser.get(search)
    
    # Clear screen based on OS
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print(f"[+] Website {search} opened successfully!")
    input("Press Enter to close the browser...")
    browser.quit()

except Exception as e:
    print(f"Error opening browser: {e}")
