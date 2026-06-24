"""
Tracks every property the digest has ever sent, forever, so a later run --
later today or any future day -- never pitches the same lead twice. An
append-only plain-text file, one "market_key:apn" identifier per line.
Intentionally a flat file over a database: this is a low-volume daily list,
and a flat file is trivial to inspect, diff, or hand-edit if needed.

Filtering happens in run.py before drafting a pitch, not just before
sending -- skipping an already-sent lead also skips its Anthropic API call.
"""
import os

SENT_LOG_PATH = os.environ.get("SENT_LOG_PATH") or "sent_properties.log"


def lead_key(market, lead):
    # Namespaced by market so two different counties can never collide on
    # APN, and so the same physical parcel re-appearing under a different
    # market key (shouldn't happen, but cheap insurance) isn't conflated.
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
