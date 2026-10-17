#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageForge 2.0 — cross-platform image search, download and gallery CLI.

Install: python -m pip install requests beautifulsoup4 pillow ddgs
Usage:   python imageforge.py
         python imageforge.py search 'nebula' --source commons --limit 10
         python imageforge.py search 'galaxy' --source wallpaperscraft --limit 5
         python imageforge.py search 'forest' --source web --limit 12
         python imageforge.py gallery
         python imageforge.py list
         python imageforge.py verify

Services can throttle or change markup. Downloaded images may have copyright
restrictions; verify permissions and attribution before publishing/reusing.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_VERSION = "2.0.0"
DEFAULT_ROOT = Path.cwd() / "Images"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
PIL_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "TIFF": ".tif"}
MAX_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
HEADERS = {
    "User-Agent": "ImageForge/2.0 (cross-platform desktop image downloader; https://www.mediawiki.org/wiki/API:Etiquette)",
    "Accept": "text/html,application/json,image/avif,image/webp,image/*;q=0.9,*/*;q=0.5",
}
LOG = logging.getLogger("imageforge")


@dataclass(frozen=True)
class ImageResult:
    source: str
    url: str
    title: str
    page_url: str = ""
    creator: str = ""
    license: str = "Unknown — check source"
    referer: str = ""


@dataclass
class Settings:
    root: Path = DEFAULT_ROOT
    limit: int = 10
    timeout: int = 18
    max_mb: int = 25
    min_width: int = 0
    min_height: int = 0
    delay: float = 0.25


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def slugify(value: str, length: int = 65) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
