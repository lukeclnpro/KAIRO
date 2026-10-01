"""Couche HTTP standard avec validation d’URL et retries GET/HEAD bornés."""

from __future__ import annotations

import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def validate_http_url(url):
    parsed = urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Seules les URL absolues HTTP et HTTPS sont autorisées.")
    return str(url)


def open_url(request, timeout=10, retries=1) -> Any:
    url = request.full_url if isinstance(request, Request) else str(request)
    validate_http_url(url)
    method = request.get_method().upper() if isinstance(request, Request) else "GET"
    retry_limit = max(0, int(retries)) if method in {"GET", "HEAD"} else 0

    for attempt in range(retry_limit + 1):
        try:
            response = urlopen(request, timeout=timeout)
            if response is None:
                raise URLError("Le client HTTP n'a pas reçu de réponse.")
            return response
        except HTTPError:
            raise
        except (URLError, TimeoutError, OSError):
            if attempt >= retry_limit:
                raise
            time.sleep(min(0.1 * (2 ** attempt), 0.5))


__all__ = ("Request", "open_url", "validate_http_url")