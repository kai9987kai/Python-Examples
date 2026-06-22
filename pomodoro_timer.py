#!/usr/bin/env python3
"""
Script Name     : pomodoro_timer.py
Description     : A professional, ANSI-colored command-line Pomodoro study timer
                  featuring live progress bars, session tracking, session-transition
                  sound alarms, and a clean pause/skip menu.
"""

import sys
import time

# ANSI color codes for rich CLI aesthetics
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"


# Try to reconfigure stdout/stderr to support UTF-8 on Windows consoles
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass


def play_beep():
    """Triggers a cross-platform beep or system bell."""
    try:
        import winsound
        # Frequency 1000Hz, duration 600ms
        winsound.Beep(1000, 600)
    except ImportError:
        # Fallback to system bell character
        sys.stdout.write('\a')
        sys.stdout.flush()


def format_time(seconds):
    """Formats raw seconds into MM:SS format."""
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"


def draw_progress_bar(percent, color, elapsed, total):
    """Draws an in-place updating progress bar."""
    bar_length = 30
    filled_length = int(bar_length * percent // 100)
    
    # Try block characters first, fall back to ASCII if encoding fails
    try:
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        time_left = format_time(total - elapsed)
        sys.stdout.write(
            f"\r{color}[{bar}] {percent:3d}% | {time_left} left | {format_time(elapsed)} elapsed{RESET}"
        )
        sys.stdout.flush()
    except UnicodeEncodeError:
        bar = "#" * filled_length + "-" * (bar_length - filled_length)
        time_left = format_time(total - elapsed)
        sys.stdout.write(
            f"\r{color}[{bar}] {percent:3d}% | {time_left} left | {format_time(elapsed)} elapsed{RESET}"
        )
        sys.stdout.flush()


def run_timer(duration_seconds, session_name, color):
    """Runs the timer for a specific duration, handling pause/skip signals."""
    print(f"\n{BOLD}{color}--- Starting Session: {session_name} ({format_time(duration_seconds)}) ---{RESET}")
    play_beep()
    
    elapsed = 0
    while elapsed < duration_seconds:
        try:
            percent = int((elapsed / duration_seconds) * 100)
            draw_progress_bar(percent, color, elapsed, duration_seconds)
            time.sleep(1)
            elapsed += 1
        except KeyboardInterrupt:
            # Handle user pause/skip menu
            print(f"\n\n{YELLOW}{BOLD}[PAUSED]{RESET} Session: {session_name}")
            print(f"Options: [c]ontinue, [s]kip session, [q]uit timer")
            
            while True:
                choice = input("Select an option: ").strip().lower()
                if choice == 'c':
                    print(f"{GREEN}Resuming {session_name}...{RESET}")
                    # Re-draw the bar before resuming loop
                    percent = int((elapsed / duration_seconds) * 100)
                    draw_progress_bar(percent, color, elapsed, duration_seconds)
                    break
                elif choice == 's':
                    print(f"{YELLOW}Skipping {session_name}.{RESET}")
                    return "skip"
                elif choice == 'q':
                    print(f"{RED}Quitting Pomodoro Timer. Stay productive!{RESET}")
                    sys.exit(0)
                else:
                    print("Invalid option. Enter 'c', 's', or 'q'.")
                    
    draw_progress_bar(100, color, duration_seconds, duration_seconds)
    print(f"\n{BOLD}{GREEN}✓ Session Completed!{RESET}")
    play_beep()
    time.sleep(1)  # Brief pause after completion
    return "done"


def main():
    print(f"{BOLD}{CYAN}========================================={RESET}")
    print(f"{BOLD}{CYAN}      PYTHON CLI POMODORO TIMER          {RESET}")
    print(f"{BOLD}{CYAN}========================================={RESET}")
    print("Default Settings: Work: 25m, Short Break: 5m, Long Break: 15m")
    
    try:
        use_custom = input("Configure custom intervals? (y/N): ").strip().lower()
        if use_custom == 'y':
            work_min = float(input("Enter Work minutes: "))
            short_min = float(input("Enter Short Break minutes: "))
            long_min = float(input("Enter Long Break minutes: "))
        else:
            work_min = 25.0
            short_min = 5.0
            long_min = 15.0
    except (ValueError, KeyboardInterrupt):
        print(f"\n{YELLOW}Invalid input or interrupted. Using default settings.{RESET}")
        work_min = 25.0
        short_min = 5.0
        long_min = 15.0

    work_sec = int(work_min * 60)
    short_sec = int(short_min * 60)
    long_sec = int(long_min * 60)

    session_count = 0
    
    print(f"\n{BOLD}Press Ctrl+C at any time during a session to Pause/Skip/Quit.{RESET}")
    
    while True:
        session_count += 1
        # 1. Work Session
        run_timer(work_sec, f"Work Session #{session_count}", RED)
        
        # 2. Break Session (Long break every 4th session, otherwise short break)
        if session_count % 4 == 0:
            run_timer(long_sec, "Long Break", CYAN)
        else:
            run_timer(short_sec, "Short Break", GREEN)
            
        print(f"\n{BOLD}{YELLOW}Current cycle stats: {session_count} Work session(s) completed.{RESET}")
        
        try:
            nxt = input("\nStart next cycle? (Y/n): ").strip().lower()
            if nxt == 'n':
                print(f"\n{BOLD}{CYAN}Great job! You completed {session_count} work session(s). Goodbye!{RESET}")
                break
        except KeyboardInterrupt:
            print(f"\n\n{BOLD}{CYAN}Great job! You completed {session_count} work session(s). Goodbye!{RESET}")
            break


if __name__ == "__main__":
    main()
