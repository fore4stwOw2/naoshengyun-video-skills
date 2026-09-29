"""Seedance video generation client for the naoshengyun gateway.

Pure standard-library implementation so the MCP server can run under any
Python 3.9+ interpreter without installing packages.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://token.naoshengyun.com"
DEFAULT_MODEL = "doubao-seedance-2-0-fast-260128"

MODELS = [
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-lite-t2v",
    "doubao-seedance-1-0-lite-i2v",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-2-0-mini-260615",
    "doubao-seedance-2-5-260628",
]

RESOLUTIONS = ["480p", "720p", "1080p", "4k"]
RATIOS = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]
ROLES = ["first_frame", "last_frame", "reference_image", "reference_video", "reference_audio"]

TERMINAL_OK = {"completed", "succeeded"}
TERMINAL_BAD = {"failed", "cancelled", "canceled", "expired"}


def _build_ssl_context() -> ssl.SSLContext:
    """Build a verifying SSL context that works on stock macOS Python builds.

    python.org installers ship without a populated OpenSSL trust store unless the
    bundled "Install Certificates.command" has been run, which makes urllib fail
    with CERTIFICATE_VERIFY_FAILED even though curl succeeds. Fall back to the
    certifi bundle, then to well-known system bundle locations. Verification is
    never disabled.
    """
    context = ssl.create_default_context()
    probe = ssl.get_default_verify_paths()
    if (probe.cafile and os.path.exists(probe.cafile)) or (
        probe.capath and os.path.isdir(probe.capath)
    ):
        return context

    candidates = []
    try:
        import certifi

        candidates.append(certifi.where())
    except Exception:
        pass
    candidates += [
        "/etc/ssl/cert.pem",
        "/usr/local/etc/openssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                context.load_verify_locations(cafile=path)
                return context
            except Exception:
                continue
    return context


_SSL_CONTEXT = _build_ssl_context()


class SeedanceError(RuntimeError):
    """Raised when the gateway reports an error or the request cannot complete."""

    def __init__(self, message: str, *, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"error": str(self)}
        if self.code:
            out["code"] = self.code
        if self.status:
            out["http_status"] = self.status
        return out


def redact(text: str) -> str:
    """Remove anything that looks like an API key from user-facing text."""
    import re

    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***REDACTED***", text or "")


@dataclass
class SeedanceClient:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 60.0
    _diagnostics: List[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.api_key = (self.api_key or os.environ.get("SEEDANCE_API_KEY", "")).strip()
        base = (self.base_url or os.environ.get("SEEDANCE_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.base_url = base.rstrip("/")
        if not self.api_key:
            raise SeedanceError(
                "Missing API key. Set the SEEDANCE_API_KEY environment variable "
                "in the MCP server configuration.",
                code="API_KEY_REQUIRED",
            )

    # ---------------------------------------------------------------- transport

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL_CONTEXT) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return self._parse(raw, resp.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise self._http_error(raw, exc.code) from None
        except urllib.error.URLError as exc:
            raise SeedanceError(
                f"Cannot reach the gateway at {self.base_url}: {redact(str(exc.reason))}",
                code="NETWORK_ERROR",
            ) from None

    @staticmethod
    def _parse(raw: str, status: int) -> Dict[str, Any]:
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise SeedanceError(
                f"Gateway returned a non-JSON response (HTTP {status}): {redact(raw[:300])}",
                code="BAD_RESPONSE",
                status=status,
            ) from None
        if not isinstance(parsed, dict):
            raise SeedanceError(
                f"Gateway returned an unexpected JSON type: {type(parsed).__name__}",
                code="BAD_RESPONSE",
                status=status,
            )
        return parsed

    @staticmethod
    def _http_error(raw: str, status: int) -> SeedanceError:
        code, message = "", ""
        try:
            body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {}

        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                message = str(err.get("message") or "")
                code = str(err.get("code") or err.get("type") or "")
            if not message:
                message = str(body.get("message") or "")
            if not code:
                code = str(body.get("code") or "")

        if not message:
            message = redact(raw[:300]) or f"HTTP {status}"

        hint = ""
        if status == 401 or code in {"INVALID_API_KEY", "API_KEY_REQUIRED"}:
            hint = (
                " The gateway rejected the credential. Verify that SEEDANCE_API_KEY is "
                "current, has video-model access, and still has quota."
            )
        elif status == 400 and code == "task_not_exist":
            hint = " The task ID is unknown to this key; task IDs are scoped to the owning key."

        return SeedanceError(redact(message) + hint, code=code, status=status)

    # -------------------------------------------------------------------- tools

    def create_video(
        self,
        prompt: str = "",
        model: str = DEFAULT_MODEL,
        seconds: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: Optional[bool] = None,
        references: Optional[List[Dict[str, str]]] = None,
        seed: Optional[int] = None,
        camera_fixed: Optional[bool] = None,
        watermark: Optional[bool] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit an asynchronous Seedance video task and return its identity."""
        model = (model or DEFAULT_MODEL).strip()
        if model not in MODELS:
            raise SeedanceError(
                f"Unknown model {model!r}. Supported models: {', '.join(MODELS)}",
                code="INVALID_MODEL",
            )

        references = references or []
        prompt = (prompt or "").strip()
        if not prompt and not references:
            raise SeedanceError(
                "Provide a prompt, at least one reference asset, or both.",
                code="INVALID_REQUEST",
            )

        metadata: Dict[str, Any] = {}
        if resolution:
            if resolution not in RESOLUTIONS:
                raise SeedanceError(
                    f"Unknown resolution {resolution!r}. Supported: {', '.join(RESOLUTIONS)}",
                    code="INVALID_REQUEST",
                )
            metadata["resolution"] = resolution
        if ratio:
            if ratio not in RATIOS:
                raise SeedanceError(
                    f"Unknown ratio {ratio!r}. Supported: {', '.join(RATIOS)}",
                    code="INVALID_REQUEST",
                )
            metadata["ratio"] = ratio

        content = self._build_content(references)
        if content:
            metadata["content"] = content
        if generate_audio is not None:
            metadata["generate_audio"] = bool(generate_audio)
        if seed is not None:
            metadata["seed"] = int(seed)
        if camera_fixed is not None:
            metadata["camera_fixed"] = bool(camera_fixed)
        if watermark is not None:
            metadata["watermark"] = bool(watermark)
        if extra_metadata:
            metadata.update(extra_metadata)

        payload: Dict[str, Any] = {"model": model}
        if prompt:
            payload["prompt"] = prompt
        if seconds not in (None, 0):
            payload["seconds"] = int(seconds)
        if metadata:
            payload["metadata"] = metadata

        body = self._request("POST", "/v1/videos", payload)
        task_id = body.get("id") or body.get("task_id")
        if not task_id:
            raise SeedanceError(
                f"Gateway accepted the request but returned no task ID: {redact(json.dumps(body)[:300])}",
                code="BAD_RESPONSE",
            )
        return {
            "task_id": task_id,
            "status": body.get("status", "queued"),
            "model": body.get("model", model),
            "created_at": body.get("created_at"),
        }

    @staticmethod
    def _build_content(references: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Translate the flat reference list into Seedance content items."""
        kind_by_role = {
            "first_frame": "image_url",
            "last_frame": "image_url",
            "reference_image": "image_url",
            "reference_video": "video_url",
            "reference_audio": "audio_url",
        }
        content: List[Dict[str, Any]] = []
        for index, ref in enumerate(references):
            if not isinstance(ref, dict):
                raise SeedanceError(
                    f"references[{index}] must be an object with 'url' and 'role'.",
                    code="INVALID_REQUEST",
                )
            url = str(ref.get("url") or "").strip()
            role = str(ref.get("role") or "reference_image").strip()
            if not url:
                raise SeedanceError(f"references[{index}] is missing 'url'.", code="INVALID_REQUEST")
            if role not in ROLES:
                raise SeedanceError(
                    f"references[{index}] has unknown role {role!r}. Supported: {', '.join(ROLES)}",
                    code="INVALID_REQUEST",
                )
            kind = kind_by_role[role]
            content.append({"type": kind, kind: {"url": url}, "role": role})
        return content

    def get_video(self, task_id: str) -> Dict[str, Any]:
        """Fetch the current state of a task, normalising the video URL location."""
        task_id = (task_id or "").strip()
        if not task_id:
            raise SeedanceError("task_id is required.", code="INVALID_REQUEST")

        body = self._request("GET", f"/v1/videos/{task_id}")
        status = str(body.get("status") or "unknown")
        result: Dict[str, Any] = {
            "task_id": body.get("id", task_id),
            "status": status,
            "progress": body.get("progress", 0),
            "model": body.get("model"),
        }

        video_url = self._extract_url(body)
        if video_url:
            result["video_url"] = video_url
        if body.get("error"):
            result["error"] = body["error"]
        if body.get("usage"):
            result["usage"] = body["usage"]
        if status in TERMINAL_OK:
            result["done"] = True
            result["ok"] = True
        elif status in TERMINAL_BAD:
            result["done"] = True
            result["ok"] = False
        else:
            result["done"] = False
        return result

    @staticmethod
    def _extract_url(body: Dict[str, Any]) -> str:
        """The URL lives in different places across gateway response shapes."""
        meta = body.get("metadata")
        if isinstance(meta, dict) and meta.get("url"):
            return str(meta["url"])
        content = body.get("content")
        if isinstance(content, dict) and content.get("video_url"):
            return str(content["video_url"])
        for key in ("video_url", "url"):
            if body.get(key):
                return str(body[key])
        return ""

    def wait_for_video(
        self,
        task_id: str,
        timeout: float = 600.0,
        poll_interval: float = 5.0,
        on_progress: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Poll until the task reaches a terminal state, the timeout, or an error."""
        deadline = time.monotonic() + max(timeout, 1.0)
        interval = max(poll_interval, 1.0)
        attempts = 0
        last: Dict[str, Any] = {}

        while True:
            attempts += 1
            last = self.get_video(task_id)
            if on_progress:
                try:
                    on_progress(last)
                except Exception:
                    pass
            if last.get("done"):
                last["poll_attempts"] = attempts
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last["done"] = False
                last["ok"] = False
                last["timed_out"] = True
                last["poll_attempts"] = attempts
                last["hint"] = (
                    f"Task {task_id} was still {last.get('status', 'pending')} after "
                    f"{int(timeout)}s. The task is still running upstream; poll "
                    f"seedance_get_video with this task_id to keep checking."
                )
                return last
            time.sleep(min(interval, remaining))

    def download(self, url: str, dest_path: str) -> Dict[str, Any]:
        """Download a generated video to disk. URLs are short-lived."""
        if not url:
            raise SeedanceError("No video URL to download.", code="INVALID_REQUEST")
        dest_path = os.path.abspath(os.path.expanduser(dest_path))
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(
                req, timeout=max(self.timeout, 120.0), context=_SSL_CONTEXT
            ) as resp, open(dest_path, "wb") as handle:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
        except urllib.error.HTTPError as exc:
            raise SeedanceError(
                f"Download failed with HTTP {exc.code}. The temporary URL may have expired.",
                code="DOWNLOAD_FAILED",
                status=exc.code,
            ) from None
        except urllib.error.URLError as exc:
            raise SeedanceError(
                f"Download failed: {redact(str(exc.reason))}", code="DOWNLOAD_FAILED"
            ) from None

        size = os.path.getsize(dest_path)
        if size == 0:
            os.remove(dest_path)
            raise SeedanceError("Download produced an empty file.", code="DOWNLOAD_FAILED")
        return {"path": dest_path, "bytes": size, "mb": round(size / 1048576, 2)}
