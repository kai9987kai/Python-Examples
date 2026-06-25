#!/usr/bin/env python3
"""
Simple local development web server.

Examples:
    python server.py
    python server.py --port 8080
    python server.py --directory ./public
    python server.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve a directory over HTTP."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to bind to. Default: 127.0.0.1 (local machine only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to serve on. Default: 8000.",
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Directory to serve. Default: current directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = os.path.abspath(args.directory)

    if not os.path.isdir(directory):
        print(f"Error: directory does not exist: {directory}", file=sys.stderr)
        return 1

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=directory,
    )

    server = http.server.ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Serving: {directory}")
    print(f"Open: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
