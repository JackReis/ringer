"""CLI provider health probe with sanitized JSON output."""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


STATUS_UP = "up"
STATUS_RATE_LIMITED = "rate-limited"
STATUS_DOWN = "down"

ERROR_HTTP = "http-error"
ERROR_MALFORMED_CONFIG = "malformed-config"
ERROR_CREDENTIAL_HEADER = "credential-header"
ERROR_NETWORK = "network-error"
ERROR_TIMEOUT = "timeout"
ERROR_PROBE = "probe-error"
ERROR_OUTPUT = "output-error"

_MISSING = object()


class ConfigError(Exception):
    """Raised when the top-level config cannot be safely interpreted."""


class ProviderValidationError(Exception):
    """Raised when one provider entry is malformed or unsafe."""

    def __init__(self, provider_name: str, category: str) -> None:
        super().__init__(category)
        self.provider_name = provider_name
        self.category = category


@dataclass(frozen=True)
class ProviderSpec:
    """Validated provider probe configuration."""

    name: str
    url: str
    method: str
    timeout_s: float
    headers: Mapping[str, str]
    body: Any = _MISSING


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable redirects so non-2xx HTTP responses remain visible."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_DEFAULT_OPENER = urllib.request.build_opener(_NoRedirectHandler()).open


def utc_timestamp() -> str:
    """Return a UTC ISO-8601 timestamp with millisecond precision."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def load_config(config_path: Path) -> List[Mapping[str, Any]]:
    """Load and validate the top-level probe config shape."""

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(ERROR_MALFORMED_CONFIG) from exc

    if not isinstance(config, dict):
        raise ConfigError(ERROR_MALFORMED_CONFIG)

    providers = config.get("providers")
    if not isinstance(providers, list):
        raise ConfigError(ERROR_MALFORMED_CONFIG)

    return providers


def probe_all(providers: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Probe providers sequentially while preserving config order."""

    return [probe_provider(provider, index) for index, provider in enumerate(providers)]


def probe_provider(
    raw_provider: Mapping[str, Any],
    index: int = 0,
    opener: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Probe one provider and return a sanitized result record."""

    try:
        spec = validate_provider(raw_provider, index)
        request = build_request(spec)
    except ProviderValidationError as exc:
        return make_result(
            provider=exc.provider_name,
            status=STATUS_DOWN,
            http_status=None,
            latency_ms=0,
            error_category=exc.category,
        )

    open_url = opener if opener is not None else _DEFAULT_OPENER
    started = time.perf_counter()
    response: Any = None

    try:
        response = open_url(request, timeout=spec.timeout_s)
        http_status = int(response.getcode())
        status, error_category = classify_http_status(http_status)
        return make_result(
            provider=spec.name,
            status=status,
            http_status=http_status,
            latency_ms=elapsed_ms(started),
            error_category=error_category,
        )
    except urllib.error.HTTPError as exc:
        http_status = int(exc.code) if isinstance(exc.code, int) else None
        status, error_category = classify_http_status(http_status)
        close_quietly(exc)
        return make_result(
            provider=spec.name,
            status=status,
            http_status=http_status,
            latency_ms=elapsed_ms(started),
            error_category=error_category,
        )
    except urllib.error.URLError as exc:
        return make_result(
            provider=spec.name,
            status=STATUS_DOWN,
            http_status=None,
            latency_ms=elapsed_ms(started),
            error_category=ERROR_TIMEOUT if is_timeout(exc) else ERROR_NETWORK,
        )
    except (TimeoutError, socket.timeout) as exc:
        return make_result(
            provider=spec.name,
            status=STATUS_DOWN,
            http_status=None,
            latency_ms=elapsed_ms(started),
            error_category=ERROR_TIMEOUT if is_timeout(exc) else ERROR_NETWORK,
        )
    except OSError:
        return make_result(
            provider=spec.name,
            status=STATUS_DOWN,
            http_status=None,
            latency_ms=elapsed_ms(started),
            error_category=ERROR_NETWORK,
        )
    except Exception:
        return make_result(
            provider=spec.name,
            status=STATUS_DOWN,
            http_status=None,
            latency_ms=elapsed_ms(started),
            error_category=ERROR_PROBE,
        )
    finally:
        close_quietly(response)


def validate_provider(raw_provider: Mapping[str, Any], index: int) -> ProviderSpec:
    """Validate one provider entry without exposing unsafe fields."""

    provider_name = provider_label(raw_provider, index)

    if not isinstance(raw_provider, dict):
        raise ProviderValidationError(provider_name, ERROR_MALFORMED_CONFIG)

    name = raw_provider.get("name")
    url = raw_provider.get("url")
    method = raw_provider.get("method")
    timeout_s = raw_provider.get("timeout_s")

    if not isinstance(name, str) or not name.strip():
        raise ProviderValidationError(provider_name, ERROR_MALFORMED_CONFIG)
    if not isinstance(url, str) or not is_http_url(url):
        raise ProviderValidationError(name, ERROR_MALFORMED_CONFIG)
    if not isinstance(method, str) or method.upper() not in {"GET", "POST"}:
        raise ProviderValidationError(name, ERROR_MALFORMED_CONFIG)
    if (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or not math.isfinite(float(timeout_s))
        or float(timeout_s) <= 0
    ):
        raise ProviderValidationError(name, ERROR_MALFORMED_CONFIG)

    headers = validate_headers(raw_provider.get("headers"), name)
    body = raw_provider.get("body", _MISSING)

    return ProviderSpec(
        name=name,
        url=url,
        method=method.upper(),
        timeout_s=float(timeout_s),
        headers=headers,
        body=body,
    )


def provider_label(raw_provider: Any, index: int) -> str:
    """Return a stable provider label for malformed provider records."""

    if isinstance(raw_provider, dict):
        name = raw_provider.get("name")
        if isinstance(name, str) and name.strip():
            return name
    return f"provider[{index}]"


def is_http_url(url: str) -> bool:
    """Return true when a URL is an absolute HTTP or HTTPS URL."""

    try:
        parsed = urllib.parse.urlsplit(url)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
    )


def validate_headers(raw_headers: Any, provider_name: str) -> Dict[str, str]:
    """Validate optional headers while rejecting credential-like names."""

    if raw_headers is None:
        return {}
    if not isinstance(raw_headers, dict):
        raise ProviderValidationError(provider_name, ERROR_MALFORMED_CONFIG)

    headers: Dict[str, str] = {}
    for header_name, header_value in raw_headers.items():
        if (
            not isinstance(header_name, str)
            or not header_name.strip()
            or contains_line_break(header_name)
            or not isinstance(header_value, str)
            or contains_line_break(header_value)
        ):
            raise ProviderValidationError(provider_name, ERROR_MALFORMED_CONFIG)
        if is_credential_header_name(header_name):
            raise ProviderValidationError(provider_name, ERROR_CREDENTIAL_HEADER)
        headers[header_name] = header_value

    return headers


def contains_line_break(value: str) -> bool:
    """Return true when a value contains disallowed header line breaks."""

    return "\r" in value or "\n" in value


def is_credential_header_name(header_name: str) -> bool:
    """Return true for header names that commonly carry credentials."""

    normalized = header_name.strip().lower().replace("_", "-")
    compact = normalized.replace(" ", "")
    return (
        "authorization" in compact
        or compact in {"api-key", "x-api-key", "apikey", "x-apikey"}
        or compact.endswith("-api-key")
        or compact.endswith("-apikey")
    )


def build_request(spec: ProviderSpec) -> urllib.request.Request:
    """Build a urllib request from a validated provider spec."""

    headers = dict(spec.headers)
    data: Optional[bytes] = None

    if spec.body is not _MISSING:
        data = json.dumps(spec.body, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        headers.setdefault("Content-Type", "application/json")

    return urllib.request.Request(
        spec.url,
        data=data,
        headers=headers,
        method=spec.method,
    )


def classify_http_status(http_status: Optional[int]) -> Tuple[str, Optional[str]]:
    """Classify an HTTP status according to the probe contract."""

    if http_status is not None and 200 <= http_status <= 299:
        return STATUS_UP, None
    if http_status == 429:
        return STATUS_RATE_LIMITED, STATUS_RATE_LIMITED
    return STATUS_DOWN, ERROR_HTTP


def make_result(
    provider: str,
    status: str,
    http_status: Optional[int],
    latency_ms: int,
    error_category: Optional[str],
) -> Dict[str, Any]:
    """Create one sanitized provider result record."""

    return {
        "provider": provider,
        "status": status,
        "http_status": http_status,
        "latency_ms": max(0, int(latency_ms)),
        "timestamp": utc_timestamp(),
        "error_category": error_category,
    }


def elapsed_ms(started: float) -> int:
    """Return nonnegative elapsed milliseconds from a perf-counter start."""

    return max(0, int(round((time.perf_counter() - started) * 1000)))


def is_timeout(exc: BaseException) -> bool:
    """Return true when an exception represents a timeout."""

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def close_quietly(resource: Any) -> None:
    """Close a resource when possible, ignoring close failures."""

    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def build_payload(providers: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the top-level JSON payload."""

    return {"generated_at": utc_timestamp(), "providers": list(providers)}


def write_json_atomic(output_path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically, creating parent directories as needed."""

    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    tmp_path = ""
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=str(parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            fd = -1
            json.dump(payload, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, output_path)
    except Exception:
        if fd >= 0:
            os.close(fd)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def run(config_path: Path, output_path: Path) -> int:
    """Run probes from config, write output, and return a process code."""

    providers = load_config(config_path)
    results = probe_all(providers)
    write_json_atomic(output_path, build_payload(results))
    return 0 if all(result["status"] == STATUS_UP for result in results) else 1


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Probe provider health endpoints.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint."""

    args = parse_args(argv)
    try:
        return run(args.config, args.output)
    except ConfigError:
        try:
            write_json_atomic(args.output, build_payload([]))
        except Exception:
            print(ERROR_OUTPUT, file=sys.stderr)
            return 1
        print(ERROR_MALFORMED_CONFIG, file=sys.stderr)
        return 1
    except Exception:
        print(ERROR_OUTPUT, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
