"""SMS fallback through the BulkSMSBD HTTP API (https://bulksmsbd.net, `POST /api/smsapi`). Off unless both
AMBULANCE_SMS_API_KEY and AMBULANCE_SMS_SENDER_ID are set; AMBULANCE_SMS_URL overrides the endpoint (tests use a fake)."""
import json
import os
import urllib.parse
import urllib.request

DEFAULT_URL = "https://bulksmsbd.net/api/smsapi"


def configured() -> bool:
    return bool(os.environ.get("AMBULANCE_SMS_API_KEY") and os.environ.get("AMBULANCE_SMS_SENDER_ID"))


def send_sms(number: str, text: str) -> str:
    """Send one text to a +8801XXXXXXXXX number. Returns "sent" or "error: ..."; never raises (SMS is only a fallback)."""
    form = {"api_key": os.environ.get("AMBULANCE_SMS_API_KEY", ""), "senderid": os.environ.get("AMBULANCE_SMS_SENDER_ID", ""),
            "number": number.lstrip("+"), "message": text,
            "type": "unicode" if any(ord(ch) > 127 for ch in text) else "text"}  # Bangla addresses need unicode
    try:  # POST body, so the API key never lands in a URL or access log
        with urllib.request.urlopen(os.environ.get("AMBULANCE_SMS_URL", DEFAULT_URL),
                                    urllib.parse.urlencode(form).encode(), timeout=10) as r:
            code = json.loads(r.read() or b"{}").get("response_code")
    except Exception as e:  # network, HTTP status, non-JSON body: record it, do not raise
        return f"error: {type(e).__name__} {getattr(e, 'code', '')}".strip()
    return "sent" if code == 202 else f"error: response_code {code}"  # 202 = accepted by the gateway
