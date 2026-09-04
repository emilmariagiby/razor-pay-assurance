import json
import urllib.request
import urllib.error

payload = {
    "stream": {
        "order_id": "ord_hero",
        "merchant_id": "merch_001",
        "events": [
            {"event_type": "payment.created",      "timestamp": "2026-08-27T10:00:01Z", "source": "gateway",  "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_A", "amount": 2500000, "metadata": {}},
            {"event_type": "payment.timeout",      "timestamp": "2026-08-27T10:00:06Z", "source": "gateway",  "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_A", "metadata": {}},
            {"event_type": "agent.retry_initiated","timestamp": "2026-08-27T10:00:31Z", "source": "agent",    "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_A", "metadata": {}},
            {"event_type": "payment.created",      "timestamp": "2026-08-27T10:00:34Z", "source": "agent",    "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_B", "amount": 2500000, "metadata": {}},
            {"event_type": "payment.authorized",   "timestamp": "2026-08-27T10:00:36Z", "source": "bank",     "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_B", "amount": 2500000, "metadata": {}},
            {"event_type": "payment.captured",     "timestamp": "2026-08-27T10:00:37Z", "source": "gateway",  "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_B", "amount": 2500000, "metadata": {}},
            {"event_type": "payment.authorized",   "timestamp": "2026-08-27T10:04:12Z", "source": "bank",     "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_A", "amount": 2500000, "metadata": {}},
            {"event_type": "payment.captured",     "timestamp": "2027-08-27T10:04:13Z", "source": "gateway",  "merchant_id": "merch_001", "customer_id": "cust_001", "order_id": "ord_hero", "payment_id": "pay_A", "amount": 2500000, "metadata": {}}
        ]
    }
}

if __name__ == "__main__":
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://localhost:8000/assurance/analyze",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            cases = result.get("cases", [])
            print(f"Cases detected: {len(cases)}")
            for c in cases:
                print(f"  violation_type:      {c.get('violation_type')}")
                print(f"  severity:            {c.get('severity')}")
                exposure = c.get("financial_exposure", 0) / 100
                print(f"  financial_exposure:  Rs {exposure:,.0f}")
                print(f"  status:              {c.get('status')}")
                print(f"  case_id:             {c.get('case_id')}")
                print()
    except urllib.error.URLError as e:
        print(f"ERROR connecting to server: {e}")
        print("Server may still be starting up.")
