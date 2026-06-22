# Python Examples Collection

A collection of useful, modernized, and dependency-free (or standard-library primary) Python scripts. This repository features utility tools, automation scripts, desktop GUI applications, and API integrations.

---

## 📂 Table of Contents
- [🖥️ Desktop GUI Applications](#-desktop-gui-applications)
- [⏱️ Interactive Command-Line Utilities](#-interactive-command-line-utilities)
- [📁 File & System Automation Tools](#-file--system-automation-tools)
- [🌐 Network, Web & API Tools](#-network-web--api-tools)
- [🧪 Math & Algorithms](#-math--algorithms)
- [⚙️ Setup & Verification](#️-setup--verification)

---

## 🖥️ Desktop GUI Applications

*   **[game_guess_number_gui.py](game_guess_number_gui.py)** - A beautiful desktop implementation of the classic "Guess the Number" game using Tkinter. Features color-coded hot/cold temperature indicators, scoring, and history listbox.
*   **[AutoClicker.py](AutoClicker.py)** - Multi-threaded mouse auto-clicker utilizing Tkinter. Clicking tasks are processed in background threads to keep the GUI responsive. Includes start/stop hotkeys and dependency safety dialogues.
*   **[calculator.py](calculator.py)** - Interactive calculator with UI integrations. Modernized with safe math functions (`sin`, `cos`, `sqrt`) and cleaned of interactive import locks.
*   **[SimpleCalculator.json](SimpleCalculator.json)** - JSON configuration metadata for calculator profiles.

---

## ⏱️ Interactive Command-Line Utilities

*   **[pomodoro_timer.py](pomodoro_timer.py)** - Professional Pomodoro CLI timer. Tracks sessions (Work, Short Break, Long Break) with a live-updating ASCII progress bar, sound alarms, and pause/skip menus.
*   **[password_generator_strength.py](password_generator_strength.py)** - Generates high-entropy passwords using Python's cryptographically secure `secrets` library and scores password complexity in bits.
*   **[SimpleStopWatch.py](SimpleStopWatch.py)** - A clean terminal stopwatch that formats elapsed time into `HH:MM:SS.d` and handles early stopping cleanly.

---

## 📁 File & System Automation Tools

*   **[batch_file_rename.py](batch_file_rename.py)** - Batch rename file extensions inside a directory. Supports path validations, `--dry-run` previews, case-insensitivity flags, and destination override safety checks.
*   **[folder_size.py](folder_size.py)** - Calculates file sizes across directories. Modernized to output the single most appropriate unit (e.g. MB, GB) and supports a sorted `--breakdown` of files/subfolders.
*   **[Organise.py](Organise.py)** - Directory organizer that moves files into categorized subfolders (e.g., Images, Documents) using cross-platform `pathlib` paths.
*   **[backup_automater_services.py](backup_automater_services.py)** - Automatically backups system configuration services.
*   **[move_files_over_x_days.py](move_files_over_x_days.py)** - Scans directories and moves files older than a specified duration.

---

## 🌐 Network, Web & API Tools

*   **[weather_fetcher.py](weather_fetcher.py)** - Fetches location details and live weather dashboards from the Open-Meteo API using standard HTTP queries. Handles Windows console UTF-8 reconfigurations.
*   **[xkcd_downloader.py](xkcd_downloader.py)** - Downloads comics via the official XKCD JSON API. Supports specific, latest, or random downloads, and saves metadata in a JSON schema next to the image.
*   **[password_cracker.py](password_cracker.py)** - Modern, cross-platform hash dictionary cracker using `hashlib`. Automatically detects MD5, SHA-1, and SHA-256 hashes and generates demo data out of the box.
*   **[portscanner.py](portscanner.py)** - High-speed multi-threaded TCP port scanner. Supports scanning port ranges (e.g., `80-443`) and exits immediately on Ctrl+C.
*   **[check_internet_con.py](check_internet_con.py)** - Verifies internet connectivity using modern Python 3 socket requests.
*   **[open_website_selenium.py](open_website_selenium.py)** - Automates browser actions using Selenium with cross-platform driver fail-safes.
*   **[markdown_to_html.py](markdown_to_html.py)** - Converts Markdown files to responsive, modern styled HTML documents using regular expressions.

---

## 🧪 Math & Algorithms

*   **[Decimal_To_Binary.py](Decimal_To_Binary.py)** - Converts floating-point and negative decimal numbers to binary strings.
*   **[Counting-sort.py](Counting-sort.py)** - Sorts lists using the linear counting sort algorithm.
*   **[Merge-sort.py](Merge-sort.py)** - Classical divide-and-conquer merge sort implementation.
*   **[QuadraticCalc.py](QuadraticCalc.py)** - Solves quadratic equations and handles imaginary complex roots cleanly.

---

## ⚙️ Setup & Verification

You can verify that the scripts compile on your environment by running:

```bash
python -m py_compile *.py
```

### Running GUI Applications
Ensure you have the required graphical dependencies installed if you run tools like `AutoClicker.py`:
```bash
pip install pyautogui keyboard
```
