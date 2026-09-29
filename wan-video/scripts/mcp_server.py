#!/usr/bin/env python3
"""MCP stdio server exposing Wan (Tongyi Wanxiang) video generation.

Speaks MCP 2024-11-05 over stdin/stdout with no third-party dependencies, so it
runs anywhere Python 3.9+ is available: WorkBuddy, Codex CLI, Claude Desktop.

Configure with environment variables:
  WAN_API_KEY     required, gateway token (sk-...)
  WAN_BASE_URL    optional, defaults to https://token.naoshengyun.com
  WAN_OUTPUT_DIR  optional, defaults to ~/Downloads/wan
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wan_client import (  # noqa: E402
    DEFAULT_MODEL,
    MEDIA_TYPES,
    MODEL_IDS,
    MODELS,
    RESOLUTIONS,
    WanClient,
    WanError,
    redact,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "wan-video"
SERVER_VERSION = "1.0.0"
MAX_WAIT_SECONDS = 1800


def log(message: str) -> None:
    """Diagnostics go to stderr; stdout is reserved for the protocol."""
    sys.stderr.write(f"[{SERVER_NAME}] {redact(message)}\n")
    sys.stderr.flush()


def default_output_dir() -> str:
    configured = os.environ.get("WAN_OUTPUT_DIR", "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), "Downloads", "wan")


# --------------------------------------------------------------------- schemas

GENERATE_PROPS: Dict[str, Any] = {
    "prompt": {
        "type": "string",
        "description": (
            "What the video should show: subject, action, camera movement, lighting. "
            "Required for t2v models; optional when a reference image is supplied."
        ),
    },
    "model": {
        "type": "string",
        "enum": MODEL_IDS,
        "default": DEFAULT_MODEL,
        "description": (
            "Wan model. wan3.0-video is the best default and handles both text-to-video "
            "and image-to-video. Call wan_list_models for the capability matrix."
        ),
    },
    "image": {
        "type": "string",
        "description": "Public https URL of the first frame, for image-to-video.",
    },
    "last_frame": {
        "type": "string",
        "description": (
            "Public https URL of the final frame, to interpolate between two stills. "
            "Requires image. Only wan3.0-video, wan3.0-video-prime and wan2.7-i2v."
        ),
    },
    "audio_url": {
        "type": "string",
        "description": "Driving audio URL for lip sync. Only wan2.7-i2v.",
    },
    "seconds": {
        "type": "integer",
        "default": 5,
        "description": "Duration in seconds. -1 asks for smart duration (wan3.0 only).",
    },
    "size": {
        "type": "string",
        "description": (
            "Output size, either width*height such as 1920*1080 or a tier (480P, 720P, "
            "1080P). Text-to-video models require width*height and default to 1920*1080; "
            "image-to-video defaults to 720P."
        ),
    },
    "resolution": {
        "type": "string",
        "enum": RESOLUTIONS,
        "description": "Resolution tier. Ignored when size is given.",
    },
    "ratio": {"type": "string", "description": "Aspect ratio, e.g. adaptive or 16:9. wan3.0 defaults to adaptive."},
    "seed": {"type": "integer", "description": "Fix the seed for reproducible output."},
    "prompt_extend": {
        "type": "boolean",
        "description": (
            "Let the service rewrite the prompt for better results. Defaults to true "
            "upstream; set false to use the prompt verbatim."
        ),
    },
    "watermark": {"type": "boolean", "description": "Add a watermark. Off by default."},
    "media": {
        "type": "array",
        "description": (
            "Advanced: explicit media array, for types that image/last_frame/audio_url "
            "cannot express. Supplying this overrides those fields."
        ),
        "items": {
            "type": "object",
            "required": ["type", "url"],
            "properties": {
                "type": {"type": "string", "enum": MEDIA_TYPES},
                "url": {"type": "string"},
            },
        },
    },
}

WAIT_PROPS: Dict[str, Any] = {
    "wait": {
        "type": "boolean",
        "default": True,
        "description": (
            "Poll until the video is ready and return its URL. Set false to submit and "
            "return the task_id immediately."
        ),
    },
    "timeout": {
        "type": "integer",
        "default": 600,
        "maximum": MAX_WAIT_SECONDS,
        "description": "Seconds to wait before returning a still-pending result.",
    },
    "download": {
        "type": "boolean",
        "default": True,
        "description": "Save the video locally. Recommended: gateway URLs expire.",
    },
    "output_path": {
        "type": "string",
        "description": "Where to save the file. Defaults to WAN_OUTPUT_DIR.",
    },
}

TOOLS = [
    {
        "name": "wan_generate_video",
        "description": (
            "Generate a video with Wan (Tongyi Wanxiang) from a text prompt, a reference "
            "image, or a first/last frame pair. By default this waits for the render to "
            "finish and saves the result locally, so a single call returns a usable file. "
            "Typical renders take 1-5 minutes."
        ),
        "inputSchema": {"type": "object", "properties": {**GENERATE_PROPS, **WAIT_PROPS}},
    },
    {
        "name": "wan_get_video",
        "description": (
            "Check a Wan task by ID. Returns status, progress and the video URL once the "
            "render completes. Use this to resume a task submitted with wait=false or one "
            "that exceeded an earlier timeout."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Task ID from wan_generate_video."},
                "wait": {"type": "boolean", "default": False, "description": "Keep polling until done."},
                "timeout": {"type": "integer", "default": 600, "maximum": MAX_WAIT_SECONDS},
                "download": {"type": "boolean", "default": True},
                "output_path": {"type": "string"},
            },
        },
    },
    {
        "name": "wan_download_video",
        "description": (
            "Download a Wan video URL to a local file. Wan returns OSS links that expire "
            "after about 24 hours, so download before then."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "Video URL from a completed task."},
                "output_path": {"type": "string", "description": "Destination file path."},
            },
        },
    },
    {
        "name": "wan_list_models",
        "description": (
            "List Wan models with their capabilities: image-to-video, last frame, "
            "audio-driven motion, smart duration, and size requirements. Call this when "
            "unsure which model supports a requested feature."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ----------------------------------------------------------------------- tools

_client: Optional[WanClient] = None


def get_client() -> WanClient:
    global _client
    if _client is None:
        _client = WanClient()
    return _client


def resolve_output_path(explicit: str, task_id: str) -> str:
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if os.path.isdir(path):
            return os.path.join(path, f"wan-{task_id}.mp4")
        return path
    return os.path.join(default_output_dir(), f"wan-{task_id}.mp4")


def maybe_download(client: WanClient, result: Dict[str, Any], args: Dict[str, Any]) -> None:
    """Persist the rendered video when the caller wants a local copy.

    Prefers the upstream URL when one is exposed, and otherwise streams the file
    from the gateway content endpoint, which is the only source on gateways that
    return status without a URL.
    """
    if not result.get("ok"):
        return
    if not args.get("download", True):
        return
    task_id = str(result.get("task_id") or "video")
    dest = resolve_output_path(str(args.get("output_path") or ""), task_id)
    url = result.get("video_url")
    try:
        if url:
            saved = client.download(url, dest)
        else:
            saved = client.download_task_content(task_id, dest)
            result["source"] = "gateway content endpoint"
        result["saved_to"] = saved["path"]
        result["size_mb"] = saved["mb"]
    except WanError as exc:
        result["download_error"] = str(exc)


def tool_generate(args: Dict[str, Any]) -> Dict[str, Any]:
    client = get_client()
    created = client.create_video(
        prompt=str(args.get("prompt") or ""),
        model=str(args.get("model") or DEFAULT_MODEL),
        image=str(args.get("image") or ""),
        last_frame=str(args.get("last_frame") or ""),
        audio_url=str(args.get("audio_url") or ""),
        seconds=args.get("seconds", 5),
        size=str(args.get("size") or ""),
        resolution=str(args.get("resolution") or ""),
        ratio=str(args.get("ratio") or ""),
        seed=args.get("seed"),
        prompt_extend=args.get("prompt_extend"),
        watermark=args.get("watermark"),
        media=args.get("media"),
    )
    task_id = created["task_id"]
    log(f"submitted task {task_id} model={created.get('model')}")

    if not args.get("wait", True):
        created["next_step"] = (
            f"Task submitted. Call wan_get_video with task_id={task_id} to check progress."
        )
        return created

    timeout = min(float(args.get("timeout") or 600), float(MAX_WAIT_SECONDS))
    result = client.wait_for_video(task_id, timeout=timeout)
    result["model"] = result.get("model") or created.get("model")
    maybe_download(client, result, args)
    return result


def tool_get(args: Dict[str, Any]) -> Dict[str, Any]:
    client = get_client()
    task_id = str(args.get("task_id") or "")
    if args.get("wait"):
        timeout = min(float(args.get("timeout") or 600), float(MAX_WAIT_SECONDS))
        result = client.wait_for_video(task_id, timeout=timeout)
    else:
        result = client.get_video(task_id)
    maybe_download(client, result, args)
    return result


def tool_download(args: Dict[str, Any]) -> Dict[str, Any]:
    client = get_client()
    dest = resolve_output_path(str(args.get("output_path") or ""), "download")
    saved = client.download(str(args.get("url") or ""), dest)
    return {"ok": True, "saved_to": saved["path"], "size_mb": saved["mb"]}


def tool_list_models(_args: Dict[str, Any]) -> Dict[str, Any]:
    models = []
    for name, spec in MODELS.items():
        models.append({
            "id": name,
            "notes": spec["notes"],
            "image_to_video": spec["image"],
            "last_frame": spec["last_frame"],
            "audio_driven": spec["audio"],
            "smart_duration": spec["smart_duration"],
            "size": "requires width*height" if spec["size_mode"] == "pixels" else "tier or width*height",
        })
    return {
        "default_model": DEFAULT_MODEL,
        "models": models,
        "resolutions": RESOLUTIONS,
        "media_types": MEDIA_TYPES,
        "output_dir": default_output_dir(),
    }


HANDLERS = {
    "wan_generate_video": tool_generate,
    "wan_get_video": tool_get,
    "wan_download_video": tool_download,
    "wan_list_models": tool_list_models,
}


# ------------------------------------------------------------------- transport


def send(message: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(request_id: Any, result: Dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def reply_error(request_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": redact(message)}})


def tool_result(payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def handle(request: Dict[str, Any]) -> None:
    method = request.get("method") or ""
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        reply(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return

    if method in {"notifications/initialized", "initialized"}:
        return

    if method == "tools/list":
        reply(request_id, {"tools": TOOLS})
        return

    if method == "ping":
        reply(request_id, {})
        return

    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            reply(request_id, tool_result({"error": f"Unknown tool: {name}"}, is_error=True))
            return
        try:
            reply(request_id, tool_result(handler(args)))
        except WanError as exc:
            log(f"tool {name} failed: {exc}")
            reply(request_id, tool_result(exc.as_dict(), is_error=True))
        except Exception as exc:  # noqa: BLE001 - never kill the server on one bad call
            log(f"tool {name} crashed: {traceback.format_exc()}")
            reply(request_id, tool_result(
                {"error": f"{type(exc).__name__}: {redact(str(exc))}"}, is_error=True))
        return

    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method.startswith("resources") else "prompts"
        reply(request_id, {key: []})
        return

    if request_id is not None:
        reply_error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    log(f"ready (base_url={os.environ.get('WAN_BASE_URL', 'default')})")
    if not os.environ.get("WAN_API_KEY", "").strip():
        log("WARNING: WAN_API_KEY is not set; tool calls will fail until it is provided.")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            log(f"ignoring malformed JSON line: {line[:120]}")
            continue
        try:
            handle(request)
        except Exception:  # noqa: BLE001
            log(f"dispatch error: {traceback.format_exc()}")
            if request.get("id") is not None:
                reply_error(request["id"], -32603, "Internal server error")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except BrokenPipeError:
        sys.exit(0)
