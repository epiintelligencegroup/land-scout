"""
Append-only dedup log — one "market_key:apn" per line.
The log is git-tracked so the cloud routine's fresh checkout picks it up.
Only updated after a confirmed send so a failed run never silently marks
properties as sent.
"""
import os

SENT_LOG_PATH = os.environ.get("SENT_LOG_PATH") or "sent_properties.log"


def lead_key(market, lead):
    return f"{market.key}:{lead.apn}"


def load_sent_keys(path=SENT_LOG_PATH):
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {line.strip() for line in f if line.strip()}


def append_sent_keys(keys, path=SENT_LOG_PATH):
    if not keys:
        return
    with open(path, "a") as f:
        for key in keys:
            f.write(key + "\n")
