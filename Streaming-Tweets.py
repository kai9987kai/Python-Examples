from __future__ import annotations

import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

import mysql.connector
from mysql.connector import Error
import tweepy


LOG = logging.getLogger("x_stream_to_mysql")

# Change these through environment variables if needed.
RULE_VALUE = os.getenv("X_RULE", "car lang:en -is:retweet")
RULE_TAG = os.getenv("X_RULE_TAG", "mysql-car-stream")


def required_env(name: str) -> str:
    """Read a required environment variable or stop with a clear error."""
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


class TweetStore:
    """Stores matching posts in MySQL."""

    def __init__(self) -> None:
        self.connection = mysql.connector.connect(
            host=required_env("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=required_env("MYSQL_USER"),
            password=required_env("MYSQL_PASSWORD"),
            database=required_env("MYSQL_DATABASE"),
            charset="utf8mb4",
            connection_timeout=10,
            autocommit=False,
        )

    def save(
        self,
        *,
        tweet_id: str,
        author_id: str | None,
        username: str | None,
        text: str,
        created_at: datetime,
        matching_rules: list[str],
        raw_payload: dict[str, Any],
    ) -> None:
        statement = """
            INSERT INTO x_posts (
                tweet_id,
                author_id,
                username,
                text,
                created_at,
                received_at,
                matching_rules,
                raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE tweet_id = tweet_id
        """

        received_at = datetime.now(timezone.utc).replace(tzinfo=None)
        created_at_utc = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        try:
            self.connection.ping(reconnect=True, attempts=3, delay=2)

            cursor = self.connection.cursor()

            try:
                cursor.execute(
                    statement,
                    (
                        tweet_id,
                        author_id,
                        username,
                        text,
                        created_at_utc,
                        received_at,
                        json.dumps(matching_rules),
                        json.dumps(raw_payload, ensure_ascii=False),
                    ),
                )

                self.connection.commit()

            finally:
                cursor.close()

        except Error:
            self.connection.rollback()
            raise

    def close(self) -> None:
        if self.connection.is_connected():
            self.connection.close()


class MySQLFilteredStream(tweepy.StreamingClient):
    """Receives filtered X posts and saves them to MySQL."""

    def __init__(
        self,
        bearer_token: str,
        store: TweetStore,
        rule_tag: str,
    ) -> None:
        super().__init__(
            bearer_token,
            wait_on_rate_limit=True,
            max_retries=10,
        )

        self.store = store
        self.rule_tag = rule_tag

    def on_response(self, response: tweepy.StreamResponse) -> None:
        """Handle a received stream response."""
        tweet = response.data

        if tweet is None:
            return

        matched_tags = [
            rule.tag
            for rule in (response.matching_rules or [])
            if rule.tag
        ]

        # Ignore posts matched only by unrelated rules in the same X project.
        if self.rule_tag not in matched_tags:
            return

        users = (response.includes or {}).get("users", [])

        usernames_by_id = {
            str(user.id): user.username
            for user in users
        }

        author_id = (
            str(tweet.author_id)
            if tweet.author_id is not None
            else None
        )

        username = usernames_by_id.get(author_id)

        created_at = tweet.created_at or datetime.now(timezone.utc)

        try:
            self.store.save(
                tweet_id=str(tweet.id),
                author_id=author_id,
                username=username,
                text=tweet.text,
                created_at=created_at,
                matching_rules=matched_tags,
                raw_payload=tweet.data,
            )

            LOG.info(
                "@%s: %s",
                username or author_id or "unknown",
                tweet.text,
            )

        except Error as exc:
            LOG.exception(
                "Database write failed for post %s: %s",
                tweet.id,
                exc,
            )

    def on_request_error(self, status_code: int) -> None:
        LOG.error("X API request failed with HTTP %s.", status_code)

        # Invalid or unauthorized credentials will not recover through retries.
        if status_code in {401, 403}:
            self.disconnect()

    def on_connection_error(self) -> None:
        LOG.warning("Stream connection lost. Tweepy will retry.")
        super().on_connection_error()


def set_up_rule(
    stream: tweepy.StreamingClient,
    rule_value: str,
    rule_tag: str,
) -> None:
    """
    Create or update this app's rule without deleting unrelated rules
    belonging to the same X developer project.
    """
    current_rules = stream.get_rules().data or []

    owned_rules = [
        rule
        for rule in current_rules
        if rule.tag == rule_tag
    ]

    if len(owned_rules) == 1 and owned_rules[0].value == rule_value:
        LOG.info("Using existing rule: %s", rule_value)
        return

    if owned_rules:
        stream.delete_rules([rule.id for rule in owned_rules])
        LOG.info("Removed old rule(s) tagged '%s'.", rule_tag)

    stream.add_rules(
        tweepy.StreamRule(
            value=rule_value,
            tag=rule_tag,
        )
    )

    LOG.info("Added rule: %s", rule_value)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bearer_token = required_env("X_BEARER_TOKEN")

    store = TweetStore()

    stream = MySQLFilteredStream(
        bearer_token=bearer_token,
        store=store,
        rule_tag=RULE_TAG,
    )

    def stop_stream(*_: object) -> None:
        LOG.info("Stopping stream...")
        stream.disconnect()

    signal.signal(signal.SIGINT, stop_stream)
    signal.signal(signal.SIGTERM, stop_stream)

    try:
        set_up_rule(stream, RULE_VALUE, RULE_TAG)

        LOG.info("Listening for matching posts. Press Ctrl+C to stop.")

        stream.filter(
            expansions=["author_id"],
            tweet_fields=["author_id", "created_at", "lang"],
            user_fields=["username"],
        )

    finally:
        store.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
