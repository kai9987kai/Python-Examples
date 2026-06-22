#!/usr/bin/env python3
"""
Post text and optional images to X from the terminal.

Install:
    python -m pip install --upgrade tweepy

Set these environment variables before running:
    X_CONSUMER_KEY
    X_CONSUMER_SECRET
    X_ACCESS_TOKEN
    X_ACCESS_TOKEN_SECRET

Examples:
    python x_post.py --text "Hello from Python"
    python x_post.py --image ./photo.jpg --text "A photo"
    python x_post.py --interactive
    python x_post.py --text "Check this" --image one.jpg --image two.png
    python x_post.py --interactive --dry-run
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import os
from pathlib import Path
from typing import Sequence

import tweepy

MAX_IMAGES = 4
MAX_TEXT_LENGTH = 280

REQUIRED_ENV_VARS = (
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def read_multiline_text() -> str:
    print("Write your post. Submit an empty line to finish:")
    lines: list[str] = []

    while True:
        line = input()
        if not line:
            break
        lines.append(line)

    return "\n".join(lines).strip()


def get_credentials() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]

    if missing:
        raise RuntimeError(
            "Missing X API credentials. Set:\n  " + "\n  ".join(missing)
        )

    return {
        "consumer_key": os.environ["X_CONSUMER_KEY"],
        "consumer_secret": os.environ["X_CONSUMER_SECRET"],
        "access_token": os.environ["X_ACCESS_TOKEN"],
        "access_token_secret": os.environ["X_ACCESS_TOKEN_SECRET"],
    }


def build_clients() -> tuple[tweepy.API, tweepy.Client]:
    creds = get_credentials()

    oauth1 = tweepy.OAuth1UserHandler(
        creds["consumer_key"],
        creds["consumer_secret"],
        creds["access_token"],
        creds["access_token_secret"],
    )

    # Used for media upload.
    upload_api = tweepy.API(oauth1)

    # Used for publishing the final post.
    post_client = tweepy.Client(
        consumer_key=creds["consumer_key"],
        consumer_secret=creds["consumer_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
        wait_on_rate_limit=True,
    )

    return upload_api, post_client


def validate_images(image_paths: Sequence[str]) -> list[Path]:
    if len(image_paths) > MAX_IMAGES:
        raise ValueError(f"You can attach at most {MAX_IMAGES} images.")

    images: list[Path] = []

    for raw_path in image_paths:
        path = Path(raw_path).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")

        mime_type, _ = mimetypes.guess_type(path.name)
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(f"Not a recognised image file: {path.name}")

        images.append(path)

    return images


def validate_post(text: str, images: Sequence[Path]) -> None:
    if not text and not images:
        raise ValueError("Provide text, at least one image, or both.")

    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(
            f"Text is {len(text)} characters. Keep it within {MAX_TEXT_LENGTH}."
        )


def upload_images(upload_api: tweepy.API, images: Sequence[Path]) -> list[str]:
    media_ids: list[str] = []

    for image in images:
        logging.info("Uploading %s", image.name)
        media = upload_api.media_upload(filename=str(image))

        media_id = getattr(media, "media_id_string", None) or str(media.media_id)
        media_ids.append(media_id)

    return media_ids


def get_username(client: tweepy.Client) -> str | None:
    try:
        response = client.get_me(user_auth=True, user_fields=["username"])
        return response.data.username if response.data else None
    except tweepy.TweepyException:
        return None


def publish_post(text: str, image_paths: Sequence[str], dry_run: bool) -> None:
    images = validate_images(image_paths)
    validate_post(text, images)

    print(f"\nText length: {len(text)}/{MAX_TEXT_LENGTH}")

    if images:
        print("Images:", ", ".join(image.name for image in images))

    if dry_run:
        print("\nDry run complete. Nothing was posted.")
        return

    upload_api, post_client = build_clients()
    media_ids = upload_images(upload_api, images)

    logging.info("Creating post...")
    response = post_client.create_tweet(
        text=text or None,
        media_ids=media_ids or None,
        user_auth=True,
    )

    post_id = response.data["id"]
    username = get_username(post_client)

    print("\nPosted successfully.")

    if username:
        print(f"https://x.com/{username}/status/{post_id}")
    else:
        print(f"Post ID: {post_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish text and up to four images to X."
    )

    parser.add_argument("--text", help="Post text.")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="PATH",
        help="Image file path. Repeat up to four times.",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Enter text and image paths interactively.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate input without posting.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    text = args.text.strip() if args.text else ""
    image_paths = list(args.image)

    try:
        if args.interactive:
            if not text:
                text = read_multiline_text()

            while True:
                image_path = input(
                    "Optional image path (press Enter when finished): "
                ).strip()

                if not image_path:
                    break

                image_paths.append(image_path)

        if not args.interactive and not text and not image_paths:
            raise ValueError("Use --text, --image, or --interactive. See --help.")

        publish_post(text, image_paths, args.dry_run)
        return 0

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    except tweepy.TooManyRequests as error:
        logging.error("Rate limit reached. Try again later. %s", error)

    except tweepy.Unauthorized:
        logging.error(
            "Credentials were rejected. Check your keys and token permissions."
        )

    except tweepy.Forbidden as error:
        logging.error(
            "X denied the action. Confirm the app has write permission and API access. %s",
            error,
        )

    except tweepy.TweepyException as error:
        logging.error("X API error: %s", error)

    except (OSError, RuntimeError, ValueError) as error:
        logging.error("%s", error)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
