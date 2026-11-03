"""HTTPS GET to api.gleif.org only. Redirects are not followed. 404 is not retried."""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = "api.gleif.org"
MAX_BODY = 1_000_000
TIMEOUT_SECONDS = 15
MIN_INTERVAL_SECONDS = 1.0
_LAST_CALL = 0.0

_SEGMENT = re.compile(r"[A-Z0-9]{20}\Z|[a-z-]+\Z")


class HttpResult:
    def __init__(self, status: int, body: bytes, kind: str) -> None:
        self.status = status
        self.body = body
        self.kind = kind


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def build_url(segments: tuple[str, ...], query: dict[str, str]) -> str:
    if not segments or any(_SEGMENT.fullmatch(part) is None for part in segments):
        raise ValueError("path")
    if segments[0] not in {"lei-records", "fuzzycompletions"}:
        raise ValueError("path")
    path = "/api/v1/" + "/".join(segments)
    encoded = urllib.parse.urlencode(query)
    url = f"https://{HOST}{path}"
    if encoded:
        url = url + "?" + encoded
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST:
        raise ValueError("host")
    return url


class UrllibTransport:
    def __init__(self, interval: float = MIN_INTERVAL_SECONDS, opener=None) -> None:
        self.interval = interval
        self._opener = opener or build_opener()

    def get(self, segments: tuple[str, ...], query: dict[str, str]) -> HttpResult:
        global _LAST_CALL
        url = build_url(segments, query)
        wait = self.interval - (time.monotonic() - _LAST_CALL)
        if _LAST_CALL and wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": "hermes-plugin-gleif/0.1",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                _LAST_CALL = time.monotonic()
                status = int(response.status)
                body = response.read(MAX_BODY + 1)
        except urllib.error.HTTPError as exc:
            _LAST_CALL = time.monotonic()
            if exc.code in {301, 302, 303, 307, 308}:
                return HttpResult(int(exc.code), b"", "redirect")
            try:
                body = exc.read(MAX_BODY + 1)
            except Exception:
                return HttpResult(int(exc.code), b"", "truncated")
            if len(body) > MAX_BODY:
                return HttpResult(int(exc.code), b"", "truncated")
            return HttpResult(int(exc.code), body, "http")
        except TimeoutError:
            _LAST_CALL = time.monotonic()
            return HttpResult(0, b"", "timeout")
        except urllib.error.URLError:
            _LAST_CALL = time.monotonic()
            return HttpResult(0, b"", "connection")
        except Exception:
            _LAST_CALL = time.monotonic()
            return HttpResult(0, b"", "connection")
        if len(body) > MAX_BODY:
            return HttpResult(status, b"", "truncated")
        return HttpResult(status, body, "ok" if status == 200 else "http")
