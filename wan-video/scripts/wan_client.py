"""Wan (Tongyi Wanxiang) video generation client for the naoshengyun gateway.

Pure standard-library implementation so the MCP server runs under any Python 3.9+
interpreter without installing packages.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://token.naoshengyun.com"
DEFAULT_MODEL = "wan3.0-video"

# Capability matrix. Wan model families differ in ways that change how a request
# must be built, so these flags are consulted during validation rather than
# letting the gateway reject the call later.
MODELS: Dict[str, Dict[str, Any]] = {
    "wan3.0-video": {
        "notes": "Gen-3 flagship. Text-to-video and image-to-video, supports last frame and smart duration.",
        "image": True, "last_frame": True, "smart_duration": True, "audio": False,
        "size_mode": "either",
    },
    "wan3.0-video-prime": {
        "notes": "Gen-3 prime. Highest fidelity, slowest and most expensive.",
        "image": True, "last_frame": True, "smart_duration": True, "audio": False,
        "size_mode": "either",
    },
    "wan2.7-i2v": {
        "notes": "Gen-2.7 image-to-video. Supports last frame and audio-driven motion.",
        "image": True, "last_frame": True, "smart_duration": False, "audio": True,
        "size_mode": "either",
    },
    "wan2.7-t2v": {
        "notes": "Gen-2.7 text-to-video. Requires a width*height size.",
        "image": False, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "pixels",
    },
    "wan2.5-t2v-preview": {
        "notes": "Gen-2.5 text-to-video preview. Requires a width*height size.",
        "image": False, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "pixels",
    },
    "wan2.5-i2v-preview": {
        "notes": "Gen-2.5 image-to-video preview.",
        "image": True, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "either",
    },
    "wan2.2-i2v-flash": {
        "notes": "Gen-2.2 image-to-video, fastest and cheapest.",
        "image": True, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "either",
    },
    "wan2.2-i2v-plus": {
        "notes": "Gen-2.2 image-to-video, better quality than flash.",
        "image": True, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "either",
    },
    "wanx2.1-i2v-plus": {
        "notes": "Gen-2.1 image-to-video, legacy quality tier.",
        "image": True, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "either",
    },
    "wanx2.1-i2v-turbo": {
        "notes": "Gen-2.1 image-to-video, legacy fast tier.",
        "image": True, "last_frame": False, "smart_duration": False, "audio": False,
        "size_mode": "either",
    },
}

MODEL_IDS = list(MODELS)
RESOLUTIONS = ["480P", "720P", "1080P"]
MEDIA_TYPES = [
    "first_frame", "last_frame", "driving_audio", "reference_video",
    "reference_image", "reference_audio", "file", "link", "first_clip",
]

# The OpenAI-compatible surface reports lowercase status; the native Ali surface
# reports uppercase. Both are normalised through these sets.
TERMINAL_OK = {"completed", "succeeded"}
TERMINAL_BAD = {"failed", "cancelled", "canceled", "expired", "unknown_failed"}

SIZE_PIXELS = re.compile(r"^\d{2,5}\*\d{2,5}$")


class WanError(RuntimeError):
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
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***REDACTED***", text or "")


def _build_ssl_context() -> ssl.SSLContext:
    """Build a verifying SSL context that works on stock macOS Python builds.

    python.org installers ship without a populated OpenSSL trust store unless the
    bundled "Install Certificates.command" has been run, which makes urllib fail
    with CERTIFICATE_VERIFY_FAILED even though curl succeeds. Fall back to the
    certifi bundle, then to well-known system locations. Verification is never
    disabled.
    """
    context = ssl.create_default_context()
    probe = ssl.get_default_verify_paths()
    if (probe.cafile and os.path.exists(probe.cafile)) or (
        probe.capath and os.path.isdir(probe.capath)
    ):
        return context

    candidates: List[str] = []
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


@dataclass
class WanClient:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.api_key = (self.api_key or os.environ.get("WAN_API_KEY", "")).strip()
        base = (self.base_url or os.environ.get("WAN_BASE_URL") or DEFAULT_BASE_URL).strip()
        self.base_url = base.rstrip("/")
        if not self.api_key:
            raise WanError(
                "Missing API key. Set the WAN_API_KEY environment variable in the "
                "MCP server configuration.",
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
                return self._parse(resp.read().decode("utf-8", "replace"), resp.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise self._http_error(raw, exc.code) from None
        except urllib.error.URLError as exc:
            raise WanError(
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
            raise WanError(
                f"Gateway returned a non-JSON response (HTTP {status}): {redact(raw[:300])}",
                code="BAD_RESPONSE", status=status,
            ) from None
        if not isinstance(parsed, dict):
            raise WanError(
                f"Gateway returned an unexpected JSON type: {type(parsed).__name__}",
                code="BAD_RESPONSE", status=status,
            )
        return parsed

    @staticmethod
    def _http_error(raw: str, status: int) -> WanError:
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
                " The gateway rejected the credential. Verify that WAN_API_KEY is "
                "current, has video-model access, and still has quota."
            )
        elif status == 400 and code == "task_not_exist":
            hint = " The task ID is unknown to this key; task IDs are scoped to the owning key."
        elif status == 404:
            hint = (
                " This route is not deployed on the gateway. That is independent of the "
                "credential; ask the operator to enable the Wan video plugin, or point "
                "WAN_BASE_URL at a gateway that serves it."
            )

        return WanError(redact(message) + hint, code=code, status=status)

    # -------------------------------------------------------------------- tools

    def create_video(
        self,
        prompt: str = "",
        model: str = DEFAULT_MODEL,
        image: str = "",
        last_frame: str = "",
        audio_url: str = "",
        seconds: Optional[int] = 5,
        size: str = "",
        resolution: str = "",
        ratio: str = "",
        seed: Optional[int] = None,
        prompt_extend: Optional[bool] = None,
        watermark: Optional[bool] = None,
        media: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Submit an asynchronous Wan video task and return its identity."""
        model = (model or DEFAULT_MODEL).strip()
        spec = MODELS.get(model)
        if spec is None:
            raise WanError(
                f"Unknown model {model!r}. Supported models: {', '.join(MODEL_IDS)}",
                code="INVALID_MODEL",
            )

        prompt = (prompt or "").strip()
        image = (image or "").strip()
        last_frame = (last_frame or "").strip()
        audio_url = (audio_url or "").strip()
        media = media or []

        has_visual_reference = bool(image or last_frame or media)
        if not prompt and not has_visual_reference:
            raise WanError(
                "Provide a prompt, a reference image, or both.", code="INVALID_REQUEST"
            )
        if not spec["image"] and has_visual_reference:
            raise WanError(
                f"{model} is a text-to-video model and does not accept reference images. "
                f"Use an i2v model such as wan2.7-i2v, or wan3.0-video.",
                code="INVALID_REQUEST",
            )
        if not spec["image"] and not prompt:
            raise WanError(
                f"{model} is a text-to-video model, so a prompt is required.",
                code="INVALID_REQUEST",
            )
        if last_frame and not spec["last_frame"]:
            supported = [m for m, s in MODELS.items() if s["last_frame"]]
            raise WanError(
                f"{model} does not support a last frame. Models that do: {', '.join(supported)}",
                code="INVALID_REQUEST",
            )
        if audio_url and not spec["audio"]:
            supported = [m for m, s in MODELS.items() if s["audio"]]
            raise WanError(
                f"{model} does not support audio-driven video. Models that do: {', '.join(supported)}",
                code="INVALID_REQUEST",
            )

        if resolution and resolution.upper() not in RESOLUTIONS:
            raise WanError(
                f"Unknown resolution {resolution!r}. Supported: {', '.join(RESOLUTIONS)}",
                code="INVALID_REQUEST",
            )
        size = self._resolve_size(spec, model, size, resolution)

        if seconds == -1 and not spec["smart_duration"]:
            raise WanError(
                f"{model} does not support smart duration (-1). Pass an explicit number "
                f"of seconds.",
                code="INVALID_REQUEST",
            )

        payload: Dict[str, Any] = {"model": model}
        if prompt:
            payload["prompt"] = prompt
        if size:
            payload["size"] = size
        if seconds not in (None, 0):
            payload["seconds"] = int(seconds)

        # The gateway derives first/last frame from image/images. Only send the
        # explicit media array when the caller needs a type it cannot express.
        if media:
            items = self._build_media(media)
            payload.setdefault("metadata", {}).setdefault("input", {})["media"] = items
        elif image and last_frame:
            payload["images"] = [image, last_frame]
        elif image:
            payload["image"] = image
        elif last_frame:
            raise WanError(
                "A last frame needs a first frame too. Pass image as well.",
                code="INVALID_REQUEST",
            )

        if audio_url:
            payload.setdefault("metadata", {}).setdefault("input", {})["audio_url"] = audio_url

        parameters: Dict[str, Any] = {}
        if seed is not None:
            parameters["seed"] = int(seed)
        if prompt_extend is not None:
            parameters["prompt_extend"] = bool(prompt_extend)
        if watermark is not None:
            parameters["watermark"] = bool(watermark)
        if ratio:
            parameters["ratio"] = ratio
        if parameters:
            payload.setdefault("metadata", {})["parameters"] = parameters

        body = self._request("POST", "/v1/videos", payload)
        task_id = body.get("id") or body.get("task_id")
        if not task_id:
            raise WanError(
                f"Gateway accepted the request but returned no task ID: "
                f"{redact(json.dumps(body)[:300])}",
                code="BAD_RESPONSE",
            )
        return {
            "task_id": task_id,
            "status": body.get("status", "queued"),
            "model": body.get("model", model),
            "created_at": body.get("created_at"),
        }

    @staticmethod
    def _resolve_size(spec: Dict[str, Any], model: str, size: str, resolution: str) -> str:
        """Wan t2v models need explicit pixels; i2v models accept a tier."""
        size = (size or "").strip()
        resolution = (resolution or "").strip().upper()

        if size:
            if "*" not in size:
                tier = size.upper()
                if tier not in RESOLUTIONS:
                    raise WanError(
                        f"size {size!r} is neither a width*height value such as 1920*1080 "
                        f"nor a tier ({', '.join(RESOLUTIONS)}).",
                        code="INVALID_REQUEST",
                    )
                size = tier
            elif not SIZE_PIXELS.match(size):
                raise WanError(
                    f"size {size!r} is malformed. Use width*height, for example 1920*1080.",
                    code="INVALID_REQUEST",
                )
        elif resolution:
            size = resolution

        if spec["size_mode"] == "pixels":
            if not size:
                return "1920*1080"
            if "*" not in size:
                tier_pixels = {"480P": "854*480", "720P": "1280*720", "1080P": "1920*1080"}
                return tier_pixels[size]
        elif not size:
            return "720P"
        return size

    @staticmethod
    def _build_media(media: List[Dict[str, str]]) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        for index, entry in enumerate(media):
            if not isinstance(entry, dict):
                raise WanError(
                    f"media[{index}] must be an object with 'type' and 'url'.",
                    code="INVALID_REQUEST",
                )
            kind = str(entry.get("type") or "").strip()
            url = str(entry.get("url") or "").strip()
            if not url:
                raise WanError(f"media[{index}] is missing 'url'.", code="INVALID_REQUEST")
            if kind not in MEDIA_TYPES:
                raise WanError(
                    f"media[{index}] has unknown type {kind!r}. Supported: {', '.join(MEDIA_TYPES)}",
                    code="INVALID_REQUEST",
                )
            items.append({"type": kind, "url": url})
        return items

    def get_video(self, task_id: str) -> Dict[str, Any]:
        """Fetch task state, normalising status casing and the video URL location."""
        task_id = (task_id or "").strip()
        if not task_id:
            raise WanError("task_id is required.", code="INVALID_REQUEST")

        body = self._request("GET", f"/v1/videos/{task_id}")
        output = body.get("output") if isinstance(body.get("output"), dict) else {}

        # The compatible surface on this gateway reports status but omits the
        # video URL. When a task has finished, consult the native task endpoint,
        # which carries output.video_url plus the rewritten prompt.
        status_probe = str(body.get("status") or output.get("task_status") or "")
        if self._normalise_status(status_probe) in TERMINAL_OK and not self._extract_url(body, output):
            try:
                native = self._request("GET", f"/ali/api/v1/tasks/{task_id}")
            except WanError:
                native = {}
            native_output = native.get("output") if isinstance(native.get("output"), dict) else {}
            if native_output:
                output = {**output, **native_output}

        raw_status = str(body.get("status") or output.get("task_status") or "unknown")
        status = self._normalise_status(raw_status)

        result: Dict[str, Any] = {
            "task_id": body.get("id") or output.get("task_id") or task_id,
            "status": status,
            "progress": body.get("progress", 0),
            "model": body.get("model"),
        }

        video_url = self._extract_url(body, output)
        if video_url:
            result["video_url"] = video_url

        error = body.get("error")
        if not error and output.get("code"):
            error = {"code": output.get("code"), "message": output.get("message", "")}
        if error:
            result["error"] = error
        if body.get("usage"):
            result["usage"] = body["usage"]
        if output.get("actual_prompt"):
            result["actual_prompt"] = output["actual_prompt"]

        if status in TERMINAL_OK:
            result["done"], result["ok"] = True, True
        elif status in TERMINAL_BAD:
            result["done"], result["ok"] = True, False
        else:
            result["done"] = False
        return result

    @staticmethod
    def _normalise_status(raw: str) -> str:
        """Map both surfaces onto one vocabulary.

        The OpenAI-compatible surface returns queued/in_progress/completed/failed;
        the native Ali surface returns PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED.
        """
        value = (raw or "").strip()
        native = {
            "PENDING": "queued",
            "RUNNING": "in_progress",
            "SUCCEEDED": "completed",
            "FAILED": "failed",
            "CANCELED": "cancelled",
            "UNKNOWN": "unknown",
        }
        if value in native:
            return native[value]
        return value.lower()

    @staticmethod
    def _extract_url(body: Dict[str, Any], output: Dict[str, Any]) -> str:
        """The URL location differs between the two gateway surfaces."""
        if output.get("video_url"):
            return str(output["video_url"])
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
    ) -> Dict[str, Any]:
        """Poll until the task reaches a terminal state, the timeout, or an error."""
        deadline = time.monotonic() + max(timeout, 1.0)
        interval = max(poll_interval, 1.0)
        attempts = 0

        while True:
            attempts += 1
            last = self.get_video(task_id)
            if last.get("done"):
                last["poll_attempts"] = attempts
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last.update(
                    done=False, ok=False, timed_out=True, poll_attempts=attempts,
                    hint=(
                        f"Task {task_id} was still {last.get('status', 'pending')} after "
                        f"{int(timeout)}s. The task is still running upstream; poll "
                        f"wan_get_video with this task_id to keep checking."
                    ),
                )
                return last
            time.sleep(min(interval, remaining))

    def content_url(self, task_id: str) -> str:
        """Gateway endpoint that streams the finished MP4 directly.

        Used when no upstream URL is exposed; it needs the API key, so it is
        fetched through the authenticated request path rather than plain GET.
        """
        return f"{self.base_url}/v1/videos/{task_id}/content"

    def download_task_content(self, task_id: str, dest_path: str) -> Dict[str, Any]:
        """Download a finished video straight from the gateway content endpoint."""
        return self._download(self.content_url(task_id), dest_path, authenticated=True)

    def download(self, url: str, dest_path: str) -> Dict[str, Any]:
        """Download a generated video. Wan URLs are OSS links valid ~24 hours."""
        return self._download(url, dest_path, authenticated=False)

    def _download(self, url: str, dest_path: str, authenticated: bool = False) -> Dict[str, Any]:
        if not url:
            raise WanError("No video URL to download.", code="INVALID_REQUEST")
        dest_path = os.path.abspath(os.path.expanduser(dest_path))
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        if authenticated:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(
                req, timeout=max(self.timeout, 300.0), context=_SSL_CONTEXT
            ) as resp, open(dest_path, "wb") as handle:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
        except urllib.error.HTTPError as exc:
            raise WanError(
                f"Download failed with HTTP {exc.code}. The OSS URL may have expired; "
                f"Wan links last about 24 hours.",
                code="DOWNLOAD_FAILED", status=exc.code,
            ) from None
        except urllib.error.URLError as exc:
            raise WanError(f"Download failed: {redact(str(exc.reason))}", code="DOWNLOAD_FAILED") from None

        size = os.path.getsize(dest_path)
        if size == 0:
            os.remove(dest_path)
            raise WanError("Download produced an empty file.", code="DOWNLOAD_FAILED")
        return {"path": dest_path, "bytes": size, "mb": round(size / 1048576, 2)}
