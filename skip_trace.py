"""
BatchData skip trace integration.

Endpoint and field names confirmed against BatchData's own mock-server API
notebook (github.com/analyticsariel/projects/skip_tracing) and their
developer blog:
  POST https://api.batchdata.com/api/v1/property/skip-trace
  Auth: Authorization: Bearer {BATCHDATA_API_KEY}
  Request: {"requests": [{"propertyAddress": {"street","city","state","zip"}}]}
  Response per result: meta.matched, name.{first,last},
                       phoneNumbers[].{number,type,score,carrier},
                       emails[].email

Name-match check: we have the owner's name from county GIS data. BatchData
looks up the owner by property address and returns who they think owns it.
If their returned last name doesn't appear in our owner name string, we flag
the result as "name mismatch -- verify manually" rather than silently passing
a wrong number through. This is the "name + address together, not name alone"
approach: address is the lookup key, name is the verification signal.

Up to 100 properties per request. For runs with more than 100 phone leads,
requests are chunked automatically.
"""
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

BATCHDATA_URL = "https://api.batchdata.com/api/v1/property/skip-trace"


@dataclass
class PhoneResult:
    number: str
    type: str        # "mobile", "landline", "VoIP"
    score: float     # 0.0–1.0 confidence per number


@dataclass
class SkipTraceResult:
    matched: bool
    phones: List[PhoneResult] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    name_verified: bool = False   # True if BatchData's returned last name matches GIS owner name
    error: Optional[str] = None

    @property
    def best_phone(self) -> Optional[PhoneResult]:
        return self.phones[0] if self.phones else None

    @property
    def found(self) -> bool:
        return self.matched and bool(self.phones or self.emails)


def _chunk(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def batch_skip_trace(leads) -> List[Optional["SkipTraceResult"]]:
    """Skip trace a list of LandLead objects via BatchData.
    Returns results in the same order as the input list.
    Returns a list of None values if BATCHDATA_API_KEY is not set.
    Never raises -- returns SkipTraceResult(matched=False, error=...) on failure
    so a BatchData outage doesn't crash the whole daily run.
    """
    api_key = os.environ.get("BATCHDATA_API_KEY", "")
    if not api_key:
        return [None] * len(leads)

    results: List[Optional[SkipTraceResult]] = []

    for chunk in _chunk(leads, 100):
        requests_list = []
        for lead in chunk:
            # property_address sometimes includes "city" after a comma (Wake NC
            # format: "123 Main St, Raleigh") -- use only the street portion.
            street = lead.property_address.split(",")[0].strip()
            requests_list.append({
                "propertyAddress": {
                    "street": street,
                    "city": lead.city,
                    "state": lead.state,
                    "zip": lead.zip,
                }
            })

        body = json.dumps({"requests": requests_list}).encode()
        req = urllib.request.Request(
            BATCHDATA_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "curl/8.4.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            err = f"BatchData HTTP {e.code}: {e.reason}"
            results.extend([SkipTraceResult(matched=False, error=err)] * len(chunk))
            continue
        except Exception as e:
            err = f"BatchData request failed: {e}"
            results.extend([SkipTraceResult(matched=False, error=err)] * len(chunk))
            continue

        raw_results = data.get("results", data.get("data", []))
        if not isinstance(raw_results, list):
            raw_results = []

        for i, lead in enumerate(chunk):
            if i >= len(raw_results):
                results.append(SkipTraceResult(matched=False, error="no result in response"))
                continue

            r = raw_results[i]
            meta = r.get("meta", {})
            matched = bool(meta.get("matched", False))

            phones = []
            for p in r.get("phoneNumbers", []):
                num = (p.get("number") or "").strip()
                if num:
                    phones.append(PhoneResult(
                        number=num,
                        type=(p.get("type") or "unknown").lower(),
                        score=float(p.get("score") or 0),
                    ))
            phones.sort(key=lambda p: p.score, reverse=True)

            emails = [
                e["email"] for e in r.get("emails", [])
                if isinstance(e, dict) and e.get("email")
            ]

            # Verify the returned owner name matches our GIS owner name.
            # False positives (BatchData found the wrong person for this address)
            # are the main skip-trace failure mode -- a last-name mismatch is
            # the clearest signal to surface rather than silently pass through.
            resp_last = ((r.get("name") or {}).get("last") or "").upper().strip()
            owner_upper = lead.owner_name.upper()
            name_verified = bool(resp_last) and resp_last in owner_upper

            results.append(SkipTraceResult(
                matched=matched,
                phones=phones,
                emails=emails,
                name_verified=name_verified,
            ))

    return results
