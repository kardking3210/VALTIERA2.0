"""Shared bounded retry policy for transient market-provider failures."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(request, timeout: float = 15, attempts: int = 3):
    """Retry only rate limiting, server errors, and transport failures; never retry access denials."""
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            if exc.code != 429 and not 500 <= exc.code <= 599 or attempt + 1 >= attempts:
                raise
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt + 1 >= attempts:
                raise
        time.sleep(0.2 * (2 ** attempt))
    raise RuntimeError("Provider request exhausted its retry budget")
