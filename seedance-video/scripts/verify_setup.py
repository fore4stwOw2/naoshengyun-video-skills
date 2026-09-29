#!/usr/bin/env python3
"""Preflight check for the seedance-video skill.

Separates the failure modes that otherwise look alike: interpreter too old, TLS
trust store empty, gateway unreachable, credential rejected, or video route not
deployed. Run this before debugging anything else.

Usage:
    SEEDANCE_API_KEY=sk-... python3 verify_setup.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"
results: list[tuple[str, str, str]] = []


def record(level: str, check: str, detail: str) -> None:
    results.append((level, check, detail))
    icon = {PASS: "  ok", FAIL: "FAIL", WARN: "warn", INFO: "note"}[level]
    print(f"[{icon}] {check}: {detail}")


def main() -> int:
    print("seedance-video preflight\n" + "-" * 60)

    # 1. interpreter
    version = sys.version_info
    if version >= (3, 9):
        record(PASS, "python", f"{version.major}.{version.minor}.{version.micro} at {sys.executable}")
    else:
        record(FAIL, "python", f"{version.major}.{version.minor} is too old; need 3.9+")
        return summarise()

    # 2. client import and TLS trust store
    try:
        from seedance_client import DEFAULT_BASE_URL, MODELS, SeedanceClient, SeedanceError, _SSL_CONTEXT
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "import", f"cannot import seedance_client: {exc}")
        return summarise()
    record(PASS, "import", f"client loaded, {len(MODELS)} models known")

    import ssl

    if _SSL_CONTEXT.verify_mode == ssl.CERT_NONE:
        record(FAIL, "tls", "certificate verification is disabled")
    else:
        record(PASS, "tls", "certificate verification enabled with a usable CA bundle")

    base_url = (os.environ.get("SEEDANCE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    record(INFO, "gateway", base_url)

    # 3. credential presence
    api_key = os.environ.get("SEEDANCE_API_KEY", "").strip()
    if not api_key:
        record(FAIL, "credential", "SEEDANCE_API_KEY is not set")
        return summarise()
    if not api_key.startswith("sk-"):
        record(WARN, "credential", "key does not start with 'sk-'; check it was pasted correctly")
    record(PASS, "credential", f"present, {len(api_key)} chars, ends ...{api_key[-4:]}")

    # 4. reachability plus credential validity on a route known to exist
    status, body = probe(f"{base_url}/v1/models", api_key, _SSL_CONTEXT)
    if status == 0:
        record(FAIL, "reachability", f"cannot reach the gateway: {body}")
        return summarise()
    record(PASS, "reachability", f"gateway responded to GET /v1/models with HTTP {status}")

    key_ok = False
    if status == 401:
        # Compare against a definitely-invalid key: identical responses mean the
        # gateway does not recognise the configured key either.
        ctrl_status, _ = probe(f"{base_url}/v1/models", "sk-control-invalid-key-000000", _SSL_CONTEXT)
        if ctrl_status == 401:
            record(
                FAIL,
                "credential valid",
                "gateway returns 401 for this key and for a known-invalid control key: "
                "the key is not recognised. Confirm it is current and has video access.",
            )
        else:
            record(FAIL, "credential valid", f"gateway rejected the key (HTTP {status}): {body[:160]}")
    elif 200 <= status < 300:
        key_ok = True
        record(PASS, "credential valid", "gateway accepted the key")
    else:
        record(WARN, "credential valid", f"unexpected HTTP {status}: {body[:160]}")

    # 5. video route deployment, independent of credential validity
    # Probe with a model this key's group actually serves. Groups expose a subset
    # of the catalogue, so picking MODELS[0] blindly reports a misleading 503.
    probe_model = MODELS[0]
    available = list_available_models(base_url, api_key, _SSL_CONTEXT)
    if available:
        usable = [m for m in MODELS if m in available]
        record(INFO, "group catalogue", f"{len(available)} model(s) visible to this key: {', '.join(available[:6])}")
        if usable:
            probe_model = usable[0]
        else:
            record(WARN, "group catalogue",
                   "this key's group exposes no Seedance video models; generation will "
                   "return model_not_found until the group is granted one.")

    video_status, video_body = probe(
        f"{base_url}/v1/videos",
        api_key,
        _SSL_CONTEXT,
        method="POST",
        payload={"model": probe_model, "prompt": "preflight", "seconds": 5},
    )
    if video_status == 404:
        record(
            FAIL,
            "video route",
            "POST /v1/videos returns 404. The video route is not deployed on this "
            "gateway; this is independent of the key. Ask the operator to enable the "
            "Seedance video plugin, or set SEEDANCE_BASE_URL to a gateway that serves it.",
        )
    elif video_status == 401:
        record(
            WARN if key_ok else FAIL,
            "video route",
            "route exists but returned 401. Fix the credential, then re-run.",
        )
    elif 200 <= video_status < 300:
        record(PASS, "video route", "POST /v1/videos accepted a task; generation is working")
    elif video_status == 400:
        record(PASS, "video route", f"route exists and validated input (HTTP 400): {video_body[:120]}")
    elif video_status == 503 and "model_not_found" in video_body:
        record(FAIL, "video route",
               f"route exists but this key's group has no channel for {probe_model}. "
               f"Ask the operator to grant this group a Seedance video model.")
    else:
        record(WARN, "video route", f"unexpected HTTP {video_status}: {video_body[:160]}")

    return summarise()


def probe(url: str, api_key: str, context, method: str = "GET", payload=None):
    """Return (status, body). Status 0 means the request never completed."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30, context=context) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace") if exc.fp else ""
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def list_available_models(base_url: str, api_key: str, context):
    """Return the model IDs this key's group can actually reach."""
    status, body = probe(f"{base_url}/v1/models", api_key, context)
    if not (200 <= status < 300):
        return []
    try:
        data = json.loads(body).get("data", [])
    except json.JSONDecodeError:
        return []
    return [m.get("id", "") for m in data if isinstance(m, dict) and m.get("id")]


def summarise() -> int:
    failures = [r for r in results if r[0] == FAIL]
    print("-" * 60)
    if failures:
        print(f"{len(failures)} blocking issue(s):\n")
        for _, check, detail in failures:
            print(f"  - {check}: {detail}")
        print("\nSee the Troubleshooting section of SKILL.md.")
        return 1
    print("All checks passed. Video generation is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
