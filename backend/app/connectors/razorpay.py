from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from app.models.event import EventSource, EventType, FinancialEvent


EVENT_MAP = {
    "payment.authorized": EventType.PAYMENT_AUTHORIZED,
    "payment.captured": EventType.PAYMENT_CAPTURED,
    "payment.failed": EventType.PAYMENT_FAILED,
    "payment.created": EventType.PAYMENT_CREATED,
    "refund.created": EventType.REFUND_REQUESTED,
    "refund.processed": EventType.REFUND_PROCESSED,
    "refund.failed": EventType.REFUND_FAILED,
    "settlement.processed": EventType.SETTLEMENT_PROCESSED,
    "dispute.created": EventType.DISPUTE_CREATED,
}


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def normalize_webhook(payload: dict[str, Any]) -> FinancialEvent:
    """Normalize a Razorpay webhook payload into the internal event contract."""
    provider_type = payload.get("event")
    event_type = EVENT_MAP.get(provider_type)
    if event_type is None:
        raise ValueError(f"Unsupported Razorpay webhook event '{provider_type}'.")

    entity = _entity(payload)
    timestamp = payload.get("created_at") or entity.get("created_at")
    if timestamp is None:
        event_time = datetime.now(timezone.utc)
    elif isinstance(timestamp, (int, float)):
        event_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    else:
        event_time = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))

    webhook_id = payload.get("id") or payload.get("event_id")
    if not webhook_id:
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        webhook_id = f"wh_{hashlib.sha256(canonical_payload.encode()).hexdigest()[:16]}"

    return FinancialEvent(
        event_id=webhook_id,
        event_type=event_type,
        timestamp=event_time,
        source=EventSource.RAZORPAY,
        merchant_id=entity.get("merchant_id"),
        customer_id=entity.get("customer_id"),
        order_id=entity.get("order_id"),
        payment_id=entity.get("id") if provider_type.startswith("payment.") else entity.get("payment_id"),
        refund_id=entity.get("id") if provider_type.startswith("refund.") else None,
        dispute_id=entity.get("id") if provider_type.startswith("dispute.") else None,
        settlement_id=entity.get("id") if provider_type.startswith("settlement.") else None,
        amount=entity.get("amount"),
        currency=entity.get("currency", "INR"),
        metadata={"provider": "razorpay", "provider_event": provider_type},
    )


def _entity(payload: dict[str, Any]) -> dict[str, Any]:
    payload_data = payload.get("payload", {})
    for resource in ("payment", "refund", "settlement", "dispute"):
        entity = payload_data.get(resource, {}).get("entity")
        if entity:
            return entity
    raise ValueError("Razorpay webhook does not contain a supported entity.")
