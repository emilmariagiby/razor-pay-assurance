from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RazorpayClient:
    """Small server-side client for Razorpay Test Mode APIs."""

    key_id: str
    key_secret: str
    base_url: str = "https://api.razorpay.com/v1"

    @classmethod
    def from_environment(cls) -> RazorpayClient | None:
        key_id = os.getenv("RAZORPAY_KEY_ID")
        key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        enabled = os.getenv("RAZORPAY_TEST_MODE", "false").lower() == "true"
        if not enabled or not key_id or not key_secret:
            return None
        return cls(key_id=key_id, key_secret=key_secret)

    def create_refund(self, payment_id: str, amount: int, notes: dict | None = None) -> dict:
        """Create a partial/full refund; amount is in paise."""
        payload = {"amount": amount}
        if notes:
            payload["notes"] = notes
        return self._request("POST", f"/payments/{payment_id}/refund", payload)

    def fetch_payment(self, payment_id: str) -> dict:
        return self._request("GET", f"/payments/{payment_id}")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, TimeoutError) as error:
            detail = error.read().decode() if isinstance(error, HTTPError) else str(error)
            raise RuntimeError(f"Razorpay API request failed: {detail}") from error
