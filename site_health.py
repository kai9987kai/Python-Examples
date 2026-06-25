#!/usr/bin/env python3
"""
Single-host health checker: DNS, ICMP ping, TCP, HTTP(S), and TLS certificate details.

Use only against hosts you own or are authorised to monitor.
Python 3.9+; standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)


@dataclass
class CheckResult:
    status: str  # ok, warning, error, skipped
    duration_ms: int
    details: dict[str, Any]
    error: Optional[str] = None


class NoRedirect(HTTPRedirectHandler):
    """Report redirects rather than silently following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ServerHealthCheck:
    def __init__(
        self,
        host: str,
        port: int,
        scheme: str,
        path: str,
        timeout: float,
        verify_tls: bool,
        run_ping: bool,
        cert_warning_days: int,
    ) -> None:
        self.host = host
        self.port = port
        self.scheme = scheme
        self.path = path if path.startswith("/") else f"/{path}"
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.run_ping = run_ping
        self.cert_warning_days = cert_warning_days
        self.results: dict[str, CheckResult] = {}

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default_port = 443 if self.scheme == "https" else 80
        netloc = host if self.port == default_port else f"{host}:{self.port}"
        return f"{self.scheme}://{netloc}{self.path}"

    def run(self) -> dict[str, Any]:
        self._record("dns", self._check_dns)
        self._record("ping", self._check_ping if self.run_ping else self._skip_ping)
        self._record("tcp", self._check_tcp)
        self._record("http", self._check_http)

        if self.scheme == "https":
            self._record("tls", self._check_tls)
        else:
            self.results["tls"] = CheckResult(
                "skipped", 0, {"reason": "TLS applies only to HTTPS targets"}
            )

        return {
            "target": {
                "host": self.host,
                "port": self.port,
                "scheme": self.scheme,
                "url": self.url,
                "timeout_seconds": self.timeout,
                "tls_verification": self.verify_tls,
            },
            "overall_status": self._overall_status(),
            "checks": {name: asdict(result) for name, result in self.results.items()},
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _record(
        self,
        name: str,
        check: Callable[[], tuple[str, dict[str, Any]]],
    ) -> None:
        started = time.perf_counter()

        try:
            status, details = check()
            self.results[name] = CheckResult(
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000),
                details=details,
            )
        except Exception as exc:
            self.results[name] = CheckResult(
                status="error",
                duration_ms=round((time.perf_counter() - started) * 1000),
                details={},
                error=f"{type(exc).__name__}: {exc}",
            )

    def _check_dns(self) -> tuple[str, dict[str, Any]]:
        records = socket.getaddrinfo(
            self.host,
            self.port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )

        addresses: list[str] = []

        for _, _, _, _, sockaddr in records:
            ip_address = sockaddr[0]
            if ip_address not in addresses:
                addresses.append(ip_address)

        return "ok", {
            "fqdn": socket.getfqdn(self.host),
            "addresses": addresses,
            "address_count": len(addresses),
        }

    def _skip_ping(self) -> tuple[str, dict[str, Any]]:
        return "skipped", {"reason": "--no-ping was used"}

    def _check_ping(self) -> tuple[str, dict[str, Any]]:
        system = platform.system().lower()

        if system == "windows":
            command = [
                "ping",
                "-n",
                "1",
                "-w",
                str(int(self.timeout * 1000)),
                self.host,
            ]
        else:
            command = ["ping", "-c", "1", self.host]

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(self.timeout + 1, 2),
                check=False,
            )
        except FileNotFoundError:
            return "warning", {"reason": "ping command is not installed"}
        except subprocess.TimeoutExpired:
            return "warning", {"reason": "ping timed out"}

        if completed.returncode == 0:
            return "ok", {"return_code": completed.returncode}

        return "warning", {
            "return_code": completed.returncode,
            "reason": "No ICMP reply; the server may still be reachable.",
        }

    def _check_tcp(self) -> tuple[str, dict[str, Any]]:
        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        ) as connection:
            peer = connection.getpeername()

        return "ok", {"peer": f"{peer[0]}:{peer[1]}"}

    def _http_opener(self):
        handlers: list[Any] = [NoRedirect()]

        if self.scheme == "https":
            context = ssl.create_default_context()

            if not self.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

            handlers.append(HTTPSHandler(context=context))

        return build_opener(*handlers)

    def _request_status(self, method: str) -> tuple[int, dict[str, str], str]:
        request = Request(
            self.url,
            method=method,
            headers={
                "User-Agent": "ServerHealthCheck/2.0",
                "Accept": "*/*",
            },
        )

        try:
            with self._http_opener().open(request, timeout=self.timeout) as response:
                if method == "GET":
                    response.read(512)

                return response.getcode(), dict(response.headers.items()), method

        except HTTPError as exc:
            # A 4xx/5xx response proves the server responded.
            return exc.code, dict(exc.headers.items()), method

    def _check_http(self) -> tuple[str, dict[str, Any]]:
        status_code, headers, method = self._request_status("HEAD")

        # Fallback for servers that do not support HEAD.
        if status_code in {405, 501}:
            status_code, headers, method = self._request_status("GET")

        details = {
            "url": self.url,
            "method": method,
            "status_code": status_code,
            "server": headers.get("Server"),
            "content_type": headers.get("Content-Type"),
            "content_length": headers.get("Content-Length"),
            "location": headers.get("Location"),
            "strict_transport_security": headers.get("Strict-Transport-Security"),
        }

        details = {
            key: value
            for key, value in details.items()
            if value is not None
        }

        if 200 <= status_code < 400:
            return "ok", details

        if 400 <= status_code < 500:
            return "warning", details

        return "error", details

    def _check_tls(self) -> tuple[str, dict[str, Any]]:
        context = ssl.create_default_context()

        if not self.verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        ) as raw_socket:
            with context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            ) as tls_socket:
                certificate = tls_socket.getpeercert()
                der_certificate = tls_socket.getpeercert(binary_form=True)

                details: dict[str, Any] = {
                    "protocol": tls_socket.version(),
                    "cipher": tls_socket.cipher(),
                    "sha256_fingerprint": hashlib.sha256(
                        der_certificate
                    ).hexdigest(),
                }

                if certificate:
                    subject = self._dn_value(
                        certificate.get("subject", ()),
                        "commonName",
                    )
                    issuer = self._dn_value(
                        certificate.get("issuer", ()),
                        "commonName",
                    )

                    valid_from = certificate.get("notBefore")
                    valid_to = certificate.get("notAfter")

                    details.update(
                        {
                            "issued_to": subject,
                            "issued_by": issuer,
                            "serial_number": certificate.get("serialNumber"),
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                            "subject_alt_names": [
                                value
                                for kind, value in certificate.get(
                                    "subjectAltName",
                                    (),
                                )
                                if kind == "DNS"
                            ],
                        }
                    )

                    if valid_to:
                        expires_at = datetime.fromtimestamp(
                            ssl.cert_time_to_seconds(valid_to),
                            tz=timezone.utc,
                        )

                        days_remaining = math.floor(
                            (
                                expires_at - datetime.now(timezone.utc)
                            ).total_seconds()
                            / 86400
                        )

                        details["expires_at_utc"] = expires_at.isoformat()
                        details["days_until_expiry"] = days_remaining

                        if days_remaining < 0:
                            return "error", details

                        if days_remaining <= self.cert_warning_days:
                            return "warning", details

                return "ok", details

    @staticmethod
    def _dn_value(name: Any, key: str) -> Optional[str]:
        for relative_name in name:
            for attribute, value in relative_name:
                if attribute == key:
                    return value
        return None

    def _overall_status(self) -> str:
        required = {"dns", "tcp", "http"}

        if self.scheme == "https":
            required.add("tls")

        if any(self.results[name].status == "error" for name in required):
            return "error"

        if any(result.status == "warning" for result in self.results.values()):
            return "warning"

        return "ok"


def parse_target(
    target: str,
    scheme_override: Optional[str],
    port_override: Optional[int],
    path_override: Optional[str],
) -> tuple[str, int, str, str]:
    raw_target = target.strip()
    assumed_scheme = scheme_override or "https"

    parsed = urlsplit(
        raw_target
        if "://" in raw_target
        else f"{assumed_scheme}://{raw_target}"
    )

    if not parsed.hostname:
        raise ValueError(
            "Supply a hostname or URL, for example github.com "
            "or https://example.com/health"
        )

    scheme = scheme_override or parsed.scheme.lower()

    if scheme not in {"http", "https"}:
        raise ValueError("Only http and https schemes are supported")

    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid port in target: {exc}") from exc

    port = port_override or parsed_port or (
        443 if scheme == "https" else 80
    )

    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")

    path = path_override or parsed.path or "/"

    if parsed.query and not path_override:
        path = f"{path}?{parsed.query}"

    return parsed.hostname, port, scheme, path


def print_human_report(report: dict[str, Any]) -> None:
    target = report["target"]

    print(f"\nTarget: {target['url']}")
    print(f"Overall status: {report['overall_status'].upper()}\n")

    for name, result in report["checks"].items():
        print(
            f"[{result['status'].upper():7}] "
            f"{name.upper():5} ({result['duration_ms']} ms)"
        )

        if result["error"]:
            print(f"  Error: {result['error']}")

        for key, value in result["details"].items():
            if isinstance(value, (list, dict, tuple)):
                rendered = json.dumps(value)
            else:
                rendered = str(value)

            print(f"  {key}: {rendered}")

        print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check one authorised server for DNS, ping, TCP, "
            "HTTP(S), and TLS health."
        )
    )

    parser.add_argument(
        "target",
        help="Hostname or URL, e.g. example.com or https://example.com/health",
    )
    parser.add_argument(
        "--scheme",
        choices=("http", "https"),
        help="Override the URL scheme",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override the network port",
    )
    parser.add_argument(
        "--path",
        help="Override the HTTP path, e.g. /health",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-check timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--no-ping",
        action="store_true",
        help="Skip the optional ICMP ping check",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for diagnostics only",
    )
    parser.add_argument(
        "--cert-warning-days",
        type=int,
        default=30,
        help="Warn when a certificate expires within this many days",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print JSON instead of normal text output",
    )

    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    if args.cert_warning_days < 0:
        parser.error("--cert-warning-days cannot be negative")

    try:
        host, port, scheme, path = parse_target(
            args.target,
            args.scheme,
            args.port,
            args.path,
        )
    except ValueError as exc:
        parser.error(str(exc))

    checker = ServerHealthCheck(
        host=host,
        port=port,
        scheme=scheme,
        path=path,
        timeout=args.timeout,
        verify_tls=not args.insecure,
        run_ping=not args.no_ping,
        cert_warning_days=args.cert_warning_days,
    )

    report = checker.run()

    if args.json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human_report(report)

    status = report["overall_status"]

    if status == "ok":
        return 0
    if status == "warning":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
