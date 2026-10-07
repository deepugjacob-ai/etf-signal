"""Web Push notifications to the dashboard installed on phone/laptop."""
import base64, json, datetime as dt
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import webpush, WebPushException


def ensure_keys(store):
    keys = store.read("keys.json")
    if keys and keys.get("public") and keys.get("private_pem"):
        return keys
    v = Vapid()
    v.generate_keys()
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    keys = {"public": base64.urlsafe_b64encode(pub).decode().rstrip("="),
            "private_pem": v.private_pem().decode(), "created": dt.datetime.now(dt.timezone.utc).isoformat()}
    store.write({"keys.json": keys})
    return keys


def send_all(store, keys, subs, title, body, tag="signal", sub_claim="https://github.com"):
    """Send to every saved device. Removes devices whose subscription has expired. Returns (sent, errors, remaining devices)."""
    if not subs:
        return 0, [], []
    vapid = Vapid.from_pem(keys["private_pem"].encode())
    # 'sub' must be a mailto: address or a bare https://host (no path), otherwise signing fails
    from urllib.parse import urlparse
    u = urlparse(sub_claim or "")
    sub_claim = f"https://{u.netloc}" if u.scheme == "https" and u.netloc else "https://github.com"
    payload = json.dumps({"title": title, "body": body, "tag": tag})
    keep, gone, sent, errors = [], [], 0, []
    for s in subs:
        try:
            webpush(subscription_info={"endpoint": s["endpoint"], "keys": s["keys"]}, data=payload,
                    vapid_private_key=vapid, vapid_claims={"sub": sub_claim}, ttl=6 * 3600, timeout=20)
            sent += 1
            keep.append(s)
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                gone.append(s["endpoint"])   # device unsubscribed or app removed: drop it
                continue
            errors.append(f"{s.get('device','device')}: {code or e}")
            keep.append(s)
        except Exception as e:
            errors.append(f"{s.get('device','device')}: {e}")
            keep.append(s)
    if gone:
        # re-read so a device added while this ran is not lost, then drop only the expired ones
        store.refresh()
        latest = store.read("subscriptions.json", []) or []
        keep = [x for x in latest if x.get("endpoint") not in gone]
        store.write({"subscriptions.json": keep})
    return sent, errors, keep
