"""Phone diagnostics that never serialize exception messages or HTTP bodies."""
from __future__ import annotations


def phone_error(exc, stage):
    chain, statuses, seen = [], [], set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 4:
        seen.add(id(current))
        chain.append(type(current).__name__)
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and 100 <= status <= 599:
            statuses.append(str(status))
        current = current.__cause__ or current.__context__
    names = " / ".join(chain)
    if any("Timeout" in name for name in chain):
        help_text = "Apple did not respond in time. Check connectivity and reconnect."
    elif any(name in ("ConnectionError", "SSLError", "ProxyError") for name in chain):
        help_text = "Could not reach Apple securely. Check the network and reconnect."
    elif any("FailedLogin" in name or "Password" in name for name in chain):
        help_text = "Apple sign-in was rejected or could not be completed. Reconnect and check your account details."
    elif "429" in statuses:
        help_text = "Apple limited requests. Wait before reconnecting."
    elif stage == "device discovery":
        help_text = "Could not list Find My devices. Check Find My availability for this account, then reconnect."
    elif stage == "verification":
        help_text = "Apple verification did not complete. Reconnect and use the latest code."
    elif stage == "sound request":
        help_text = "Sound delivery is unconfirmed. Check your phone before trying again; the rate limit still applies."
    else:
        help_text = "Reconnect to try again. If this repeats, share this diagnostic."
    detail = names + (("; HTTP " + ",".join(statuses)) if statuses else "")
    return {"event": "phone_error", "stage": stage,
            "message": f"Phone {stage} failed ({detail}). {help_text}"}
