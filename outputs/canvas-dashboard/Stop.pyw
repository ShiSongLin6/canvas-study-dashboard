"""Stop the localhost-only Canvas dashboard, if it is running."""

from __future__ import annotations

import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8765/api/shutdown",
    data=b"{}",
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=3):
        pass
except Exception:
    pass
