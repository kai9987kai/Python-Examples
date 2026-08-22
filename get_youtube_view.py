#!/usr/bin/env python3
"""
Advanced Selenium Page Refresh / Reload Utility
================================================

Modern replacement for the original 2017 script.

Designed for:
    - Website testing
    - Development servers
    - Dashboard refresh testing
    - Cache testing
    - Page reliability testing
    - Long-running Selenium experiments

Features:
    - Chrome
    - Firefox
    - Microsoft Edge
    - Safari
    - Interactive mode
    - Command-line mode
    - Automatic https:// handling
    - URL validation
    - HH:MM:SS / MM:SS / seconds interval support
    - Headless operation where supported
    - Page-load timeouts
    - Refresh retry system
    - Exponential retry backoff
    - Graceful Ctrl+C shutdown
    - Accurate load counting
    - Detailed logging
    - Automatic WebDriver cleanup

Requires:
    pip install -U selenium

Examples:

    python refresh_runner.py example.com

    python refresh_runner.py https://example.com \
        --browser chrome \
        --interval 01:30 \
        --refreshes 10

    python refresh_runner.py example.com \
        --browser firefox \
        --interval 30 \
        --total-loads 20 \
        --headless

Author:
    Modernised version based on the original Barnaby Sandeford script.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from selenium import webdriver

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)


# ============================================================
# LOGGING
# ============================================================

LOGGER = logging.getLogger("SeleniumRefreshRunner")


# ============================================================
# CONFIGURATION MODEL
# ============================================================

@dataclass(frozen=True)
class Config:
    """
    Runtime configuration.

    url:
        Final normalised URL.

    browser:
        chrome / firefox / edge / safari.

    interval:
        Number of seconds between refresh operations.

    refreshes:
        Number of refreshes AFTER the initial page load.

    headless:
        Whether to run without a visible browser window.

    page_load_timeout:
        Maximum allowed page loading time.

    retries:
        Number of times to retry a failed refresh.
    """

    url: str

    browser: str

    interval: float

    refreshes: int

    headless: bool

    page_load_timeout: float

    retries: int


# ============================================================
# URL HANDLING
# ============================================================

def normalize_url(value: str) -> str:
    """
    Normalise and validate a user-supplied URL.

    Examples:

        google.com

    becomes:

        https://google.com

    while:

        http://example.com

    remains unchanged.
    """

    value = value.strip()

    if not value:
        raise ValueError(
            "URL cannot be empty."
        )

    # Automatically prefer HTTPS where no protocol was entered.
    if "://" not in value:
        value = "https://" + value

    parsed = urlparse(value)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        raise ValueError(
            "Only http:// and https:// URLs are supported."
        )

    if not parsed.netloc:
        raise ValueError(
            "URL must contain a valid hostname."
        )

    return value


# ============================================================
# DURATION PARSER
# ============================================================

def parse_duration(value: str) -> float:
    """
    Convert several duration formats into seconds.

    Supported formats:

        90

        90.5

        01:30

        1:02:03

    Examples:

        90
            -> 90 seconds

        02:30
            -> 150 seconds

        1:00:00
            -> 3600 seconds
    """

    value = value.strip()

    if not value:
        raise argparse.ArgumentTypeError(
            "Duration cannot be empty."
        )

    try:

        # ----------------------------------------------
        # Plain seconds
        # ----------------------------------------------

        if ":" not in value:

            seconds = float(value)

        else:

            parts = value.split(":")

            # ------------------------------------------
            # MM:SS
            # ------------------------------------------

            if len(parts) == 2:

                minutes = int(parts[0])

                seconds_part = float(parts[1])

                seconds = (
                    minutes * 60
                    + seconds_part
                )

            # ------------------------------------------
            # HH:MM:SS
            # ------------------------------------------

            elif len(parts) == 3:

                hours = int(parts[0])

                minutes = int(parts[1])

                seconds_part = float(parts[2])

                seconds = (
                    hours * 3600
                    + minutes * 60
                    + seconds_part
                )

            else:

                raise ValueError

        if seconds < 0:
            raise ValueError

        return seconds

    except ValueError as exc:

        raise argparse.ArgumentTypeError(
            "Use seconds, MM:SS or HH:MM:SS."
        ) from exc


# ============================================================
# INTEGER VALIDATION
# ============================================================

def non_negative_integer(value: str) -> int:
    """
    argparse validator for numbers >= 0.
    """

    try:

        number = int(value)

    except ValueError as exc:

        raise argparse.ArgumentTypeError(
            "Value must be an integer."
        ) from exc

    if number < 0:

        raise argparse.ArgumentTypeError(
            "Value must be 0 or greater."
        )

    return number


# ============================================================
# DRIVER FACTORY
# ============================================================

def create_driver(
    browser: str,
    headless: bool,
) -> webdriver.Remote:
    """
    Create a WebDriver for the requested browser.

    Selenium Manager in modern Selenium releases will normally
    resolve compatible drivers automatically.
    """

    browser = browser.lower()

    # ========================================================
    # GOOGLE CHROME
    # ========================================================

    if browser == "chrome":

        options = webdriver.ChromeOptions()

        if headless:

            options.add_argument(
                "--headless=new"
            )

            options.add_argument(
                "--window-size=1920,1080"
            )

        options.add_argument(
            "--disable-notifications"
        )

        return webdriver.Chrome(
            options=options
        )

    # ========================================================
    # MOZILLA FIREFOX
    # ========================================================

    if browser == "firefox":

        options = webdriver.FirefoxOptions()

        if headless:

            options.add_argument(
                "-headless"
            )

        return webdriver.Firefox(
            options=options
        )

    # ========================================================
    # MICROSOFT EDGE
    # ========================================================

    if browser == "edge":

        options = webdriver.EdgeOptions()

        if headless:

            options.add_argument(
                "--headless=new"
            )

            options.add_argument(
                "--window-size=1920,1080"
            )

        return webdriver.Edge(
            options=options
        )

    # ========================================================
    # APPLE SAFARI
    # ========================================================

    if browser == "safari":

        if headless:

            raise ValueError(
                "Safari does not support this script's "
                "headless configuration."
            )

        return webdriver.Safari()

    raise ValueError(
        f"Unsupported browser: {browser}"
    )


# ============================================================
# RETRY SYSTEM
# ============================================================

def refresh_with_retries(
    driver: webdriver.Remote,
    refresh_number: int,
    max_retries: int,
) -> bool:
    """
    Refresh the current page.

    Temporary failures are retried.

    The retry delay follows:

        1 second
        2 seconds
        4 seconds
        8 seconds

    up to a maximum delay of 8 seconds.

    Returns:
        True  -> success
        False -> all retries failed
    """

    for retry in range(
        max_retries + 1
    ):

        try:

            driver.refresh()

            return True

        except TimeoutException:

            LOGGER.warning(
                "Refresh %d timed out.",
                refresh_number,
            )

        except WebDriverException as exc:

            LOGGER.warning(
                "Refresh %d failed: %s",
                refresh_number,
                exc,
            )

        # ----------------------------------------------
        # No more retries remain.
        # ----------------------------------------------

        if retry >= max_retries:

            break

        # ----------------------------------------------
        # Exponential retry delay.
        # ----------------------------------------------

        delay = min(
            2 ** retry,
            8
        )

        LOGGER.info(
            "Retrying in %s second(s)...",
            delay,
        )

        time.sleep(delay)

    return False


# ============================================================
# MAIN AUTOMATION ENGINE
# ============================================================

def run(
    config: Config,
) -> int:
    """
    Execute the browser automation session.

    Return codes:

        0   success

        1   configuration/WebDriver failure

        2   refresh retries exhausted

        130 interrupted with Ctrl+C
    """

    driver: Optional[
        webdriver.Remote
    ] = None

    try:

        # ====================================================
        # CREATE BROWSER
        # ====================================================

        LOGGER.info(
            "Starting browser: %s",
            config.browser,
        )

        driver = create_driver(
            config.browser,
            config.headless,
        )

        # ====================================================
        # PAGE LOAD TIMEOUT
        # ====================================================

        driver.set_page_load_timeout(
            config.page_load_timeout
        )

        # ====================================================
        # INITIAL PAGE LOAD
        # ====================================================

        LOGGER.info(
            "Opening:"
        )

        LOGGER.info(
            "%s",
            config.url,
        )

        initial_start = time.monotonic()

        driver.get(
            config.url
        )

        initial_elapsed = (
            time.monotonic()
            - initial_start
        )

        LOGGER.info(
            "Initial page load completed in %.2f seconds.",
            initial_elapsed,
        )

        # ====================================================
        # TITLE INFORMATION
        # ====================================================

        try:

            title = (
                driver.title
                or "(no title)"
            )

            LOGGER.info(
                "Page title: %s",
                title,
            )

        except WebDriverException:

            LOGGER.warning(
                "Unable to obtain page title."
            )

        # ====================================================
        # ZERO REFRESH MODE
        # ====================================================

        if config.refreshes == 0:

            LOGGER.info(
                "No refreshes requested."
            )

            LOGGER.info(
                "Total page loads: 1"
            )

            return 0

        # ====================================================
        # START TIMER
        # ====================================================

        automation_start = (
            time.monotonic()
        )

        # ====================================================
        # REFRESH LOOP
        # ====================================================

        for refresh_number in range(
            1,
            config.refreshes + 1,
        ):

            LOGGER.info(
                "Waiting %.2f seconds "
                "before refresh %d/%d...",
                config.interval,
                refresh_number,
                config.refreshes,
            )

            # ----------------------------------------------
            # Wait for requested interval
            # ----------------------------------------------

            time.sleep(
                config.interval
            )

            refresh_start = (
                time.monotonic()
            )

            # ----------------------------------------------
            # Attempt refresh
            # ----------------------------------------------

            success = (
                refresh_with_retries(
                    driver,
                    refresh_number,
                    config.retries,
                )
            )

            if not success:

                LOGGER.error(
                    "Refresh %d failed "
                    "after all retry attempts.",
                    refresh_number,
                )

                return 2

            refresh_elapsed = (
                time.monotonic()
                - refresh_start
            )

            total_elapsed = (
                time.monotonic()
                - automation_start
            )

            # ----------------------------------------------
            # Read page title
            # ----------------------------------------------

            try:

                title = (
                    driver.title
                    or "(no title)"
                )

            except WebDriverException:

                title = (
                    "(title unavailable)"
                )

            # ----------------------------------------------
            # Progress information
            # ----------------------------------------------

            percent = (
                refresh_number
                / config.refreshes
                * 100
            )

            LOGGER.info(
                "Refresh %d/%d complete "
                "(%.1f%%)",
                refresh_number,
                config.refreshes,
                percent,
            )

            LOGGER.info(
                "Refresh load time: %.2fs",
                refresh_elapsed,
            )

            LOGGER.info(
                "Total elapsed time: %.2fs",
                total_elapsed,
            )

            LOGGER.info(
                "Current title: %s",
                title,
            )

        # ====================================================
        # FINISHED
        # ====================================================

        total_loads = (
            config.refreshes
            + 1
        )

        total_runtime = (
            time.monotonic()
            - automation_start
        )

        LOGGER.info(
            "Automation completed successfully."
        )

        LOGGER.info(
            "Initial loads: 1"
        )

        LOGGER.info(
            "Refreshes: %d",
            config.refreshes,
        )

        LOGGER.info(
            "Total page loads: %d",
            total_loads,
        )

        LOGGER.info(
            "Total refresh runtime: %.2fs",
            total_runtime,
        )

        return 0

    # ========================================================
    # CTRL+C
    # ========================================================

    except KeyboardInterrupt:

        LOGGER.warning(
            "Automation interrupted by user."
        )

        return 130

    # ========================================================
    # EXPECTED ERRORS
    # ========================================================

    except ValueError as exc:

        LOGGER.error(
            "Configuration error: %s",
            exc,
        )

        return 1

    except TimeoutException:

        LOGGER.error(
            "Initial page load exceeded "
            "the configured timeout."
        )

        return 1

    except WebDriverException as exc:

        LOGGER.error(
            "WebDriver failure: %s",
            exc,
        )

        return 1

    # ========================================================
    # ALWAYS CLOSE BROWSER
    # ========================================================

    finally:

        if driver is not None:

            try:

                driver.quit()

                LOGGER.info(
                    "Browser closed cleanly."
                )

            except WebDriverException:

                LOGGER.warning(
                    "Browser session was "
                    "already closed."
                )


# ============================================================
# INTERACTIVE CONFIGURATION
# ============================================================

def interactive_config() -> Config:
    """
    Ask for configuration through input().
    """

    print()
    print(
        "========================================"
    )
    print(
        "     Selenium Refresh Runner"
    )
    print(
        "========================================"
    )
    print()

    # ========================================================
    # BROWSER
    # ========================================================

    browser = input(
        "Browser "
        "[chrome/firefox/edge/safari] "
        "(chrome): "
    ).strip().lower()

    if not browser:

        browser = "chrome"

    if browser not in {
        "chrome",
        "firefox",
        "edge",
        "safari",
    }:

        raise ValueError(
            f"Unsupported browser: {browser}"
        )

    # ========================================================
    # URL
    # ========================================================

    raw_url = input(
        "URL: "
    )

    url = normalize_url(
        raw_url
    )

    # ========================================================
    # REFRESH COUNT
    # ========================================================

    while True:

        try:

            raw_refreshes = input(
                "Number of refreshes: "
            ).strip()

            refreshes = (
                non_negative_integer(
                    raw_refreshes
                )
            )

            break

        except argparse.ArgumentTypeError as exc:

            print(
                f"Invalid value: {exc}"
            )

    # ========================================================
    # INTERVAL
    # ========================================================

    while True:

        try:

            raw_interval = input(
                "Refresh interval "
                "[seconds/MM:SS/HH:MM:SS]: "
            ).strip()

            interval = parse_duration(
                raw_interval
            )

            break

        except argparse.ArgumentTypeError as exc:

            print(
                f"Invalid value: {exc}"
            )

    # ========================================================
    # HEADLESS
    # ========================================================

    headless = False

    if browser != "safari":

        raw_headless = input(
            "Run headless? [y/N]: "
        ).strip().lower()

        headless = (
            raw_headless
            in {
                "y",
                "yes",
            }
        )

    return Config(
        url=url,
        browser=browser,
        interval=interval,
        refreshes=refreshes,
        headless=headless,
        page_load_timeout=45.0,
        retries=2,
    )


# ============================================================
# COMMAND-LINE ARGUMENTS
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """
    Build command-line parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Cross-browser Selenium "
            "page-refresh utility for "
            "legitimate website testing."
        )
    )

    # ========================================================
    # URL
    # ========================================================

    parser.add_argument(
        "url",
        nargs="?",
        help=(
            "URL to load. "
            "https:// is automatically "
            "added when omitted."
        ),
    )

    # ========================================================
    # BROWSER
    # ========================================================

    parser.add_argument(
        "-b",
        "--browser",
        choices=(
            "chrome",
            "firefox",
            "edge",
            "safari",
        ),
        default="chrome",
        help=(
            "Browser to use "
            "(default: chrome)."
        ),
    )

    # ========================================================
    # INTERVAL
    # ========================================================

    parser.add_argument(
        "-i",
        "--interval",
        type=parse_duration,
        default=60.0,
        help=(
            "Delay between refreshes. "
            "Accepts seconds, MM:SS "
            "or HH:MM:SS. "
            "Default: 60 seconds."
        ),
    )

    # ========================================================
    # LOAD COUNT
    # ========================================================

    count_group = (
        parser.add_mutually_exclusive_group()
    )

    count_group.add_argument(
        "-r",
        "--refreshes",
        type=non_negative_integer,
        default=None,
        help=(
            "Number of refreshes AFTER "
            "the initial page load."
        ),
    )

    count_group.add_argument(
        "--total-loads",
        type=non_negative_integer,
        default=None,
        help=(
            "Total number of page loads, "
            "including the initial load."
        ),
    )

    # ========================================================
    # HEADLESS
    # ========================================================

    parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run browser without a visible "
            "window where supported."
        ),
    )

    # ========================================================
    # PAGE LOAD TIMEOUT
    # ========================================================

    parser.add_argument(
        "--page-load-timeout",
        type=float,
        default=45.0,
        help=(
            "Maximum page loading time "
            "in seconds. Default: 45."
        ),
    )

    # ========================================================
    # RETRIES
    # ========================================================

    parser.add_argument(
        "--retries",
        type=non_negative_integer,
        default=2,
        help=(
            "Number of retries following "
            "a failed refresh. Default: 2."
        ),
    )

    # ========================================================
    # VERBOSE
    # ========================================================

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Enable verbose/debug logging."
        ),
    )

    return parser


# ============================================================
# PROGRAM ENTRY
# ============================================================

def main() -> int:
    """
    Main entry point.
    """

    parser = build_parser()

    args = parser.parse_args()

    # ========================================================
    # LOGGING CONFIGURATION
    # ========================================================

    logging.basicConfig(
        level=(
            logging.DEBUG
            if args.verbose
            else logging.INFO
        ),
        format=(
            "%(asctime)s | "
            "%(levelname)-8s | "
            "%(message)s"
        ),
        datefmt="%H:%M:%S",
    )

    # ========================================================
    # INTERACTIVE MODE
    # ========================================================

    if args.url is None:

        try:

            config = (
                interactive_config()
            )

        except KeyboardInterrupt:

            print()

            LOGGER.info(
                "Cancelled."
            )

            return 130

        except ValueError as exc:

            LOGGER.error(
                "%s",
                exc,
            )

            return 1

    # ========================================================
    # COMMAND-LINE MODE
    # ========================================================

    else:

        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        try:

            url = normalize_url(
                args.url
            )

        except ValueError as exc:

            parser.error(
                str(exc)
            )

        # ----------------------------------------------------
        # PAGE LOAD TIMEOUT
        # ----------------------------------------------------

        if args.page_load_timeout <= 0:

            parser.error(
                "--page-load-timeout "
                "must be greater than 0."
            )

        # ----------------------------------------------------
        # NUMBER OF REFRESHES
        # ----------------------------------------------------

        if args.total_loads is not None:

            if args.total_loads < 1:

                parser.error(
                    "--total-loads must "
                    "be at least 1."
                )

            refreshes = (
                args.total_loads
                - 1
            )

        else:

            refreshes = (
                args.refreshes
                if args.refreshes is not None
                else 1
            )

        # ----------------------------------------------------
        # SAFARI HEADLESS VALIDATION
        # ----------------------------------------------------

        if (
            args.browser == "safari"
            and args.headless
        ):

            parser.error(
                "--headless is not "
                "supported by Safari "
                "in this utility."
            )

        # ----------------------------------------------------
        # BUILD CONFIG
        # ----------------------------------------------------

        config = Config(
            url=url,
            browser=args.browser,
            interval=args.interval,
            refreshes=refreshes,
            headless=args.headless,
            page_load_timeout=(
                args.page_load_timeout
            ),
            retries=args.retries,
        )

    # ========================================================
    # DISPLAY CONFIGURATION
    # ========================================================

    LOGGER.info(
        "Configuration:"
    )

    LOGGER.info(
        "  URL: %s",
        config.url,
    )

    LOGGER.info(
        "  Browser: %s",
        config.browser,
    )

    LOGGER.info(
        "  Refresh interval: %.2fs",
        config.interval,
    )

    LOGGER.info(
        "  Refreshes: %d",
        config.refreshes,
    )

    LOGGER.info(
        "  Total loads: %d",
        config.refreshes + 1,
    )

    LOGGER.info(
        "  Headless: %s",
        config.headless,
    )

    LOGGER.info(
        "  Page timeout: %.2fs",
        config.page_load_timeout,
    )

    LOGGER.info(
        "  Retry count: %d",
        config.retries,
    )

    # ========================================================
    # RUN
    # ========================================================

    return run(
        config
    )


# ============================================================
# EXECUTE
# ============================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
