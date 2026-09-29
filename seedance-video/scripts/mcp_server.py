#!/usr/bin/env python3
"""MCP stdio server exposing Seedance video generation.

Speaks MCP 2024-11-05 over stdin/stdout with no third-party dependencies, so it
runs anywhere Python 3.9+ is available: WorkBuddy, Codex CLI, Claude Desktop.

Configure with environment variables:
  SEEDANCE_API_KEY    required, gateway token (sk-...)
  SEEDANCE_BASE_URL   optional, defaults to https://token.naoshengyun.com
  SEEDANCE_OUTPUT_DIR optional, defaults to ~/Downloads/seedance
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seedance_client import (  # noqa: E402
    DEFAULT_MODEL,
    MODELS,
    RATIOS,
    RESOLUTIONS,
    ROLES,
    SeedanceClient,
    SeedanceError,
    redact,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "seedance-video"
SERVER_VERSION = "1.0.0"

MAX_WAIT_SECONDS = 1800


def log(message: str) -> None:
    """Diagnostics must go to stderr; stdout is reserved for the protocol."""
    sys.stderr.write(f"[{SERVER_NAME}] {redact(message)}\n")
    sys.stderr.flush()


def default_output_dir() -> str:
    configured = os.environ.get("SEEDANCE_OUTPUT_DIR", "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(os.path.expanduser("~"), "Downloads", "seedance")


# --------------------------------------------------------------------- schemas

REFERENCE_SCHEMA = {
    "type": "array",
    "description": (
        "Reference assets for image-to-video or reference-to-video. Each item needs a "
        "public https URL (or a data URL) plus a role."
    ),
    "items": {
        "type": "object",
        "required": ["url", "role"],
        "properties": {
            "url": {"type": "string", "description": "Public https URL or data URL."},
            "role": {
                "type": "string",
                "enum": ROLES,
                "description": (
                    "first_frame / last_frame drive the start and end of the shot; "
                    "reference_image, reference_video and reference_audio guide style, "
                    "motion and lip sync."
                ),
            },
        },
    },
}

GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": (
                "What the video should show. Describe subject, action, camera movement "
                "and lighting. Required unless references are supplied."
            ),
        },
        "model": {
            "type": "string",
            "enum": MODELS,
            "default": DEFAULT_MODEL,
            "description": (
                "Seedance model. The 2-0-fast variant is the best default for cost and "
                "speed; use 2-0 or 2-5 for higher fidelity, lite-i2v for image-to-video."
            ),
        },
        "seconds": {
            "type": "integer",
            "minimum": -1,
            "maximum": 3600,
            "default": 5,
            "description": "Duration in seconds. -1 asks the model to choose.",
        },
        "resolution": {"type": "string", "enum": RESOLUTIONS, "default": "720p"},
        "ratio": {"type": "string", "enum": RATIOS, "default": "16:9"},
        "generate_audio": {"type": "boolean", "description": "Generate a soundtrack."},
        "references": REFERENCE_SCHEMA,
        "seed": {"type": "integer", "description": "Fix the seed for reproducible output."},
        "camera_fixed": {"type": "boolean", "description": "Lock the camera in place."},
        "watermark": {"type": "boolean", "description": "Add an AI watermark."},
    },
}

WAIT_PROPS = {
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
        "description": (
            "Save the video locally. Strongly recommended: gateway URLs are temporary."
        ),
    },
    "output_path": {
        "type": "string",
        "description": "Where to save the file. Defaults to SEEDANCE_OUTPUT_DIR.",
    },
}

TOOLS = [
    {
        "name": "seedance_generate_video",
        "description": (
            "Generate a video with Doubao Seedance from a text prompt and/or reference "
            "images, video and audio. By default this waits for the render to finish and "
            "saves the result locally, so a single call returns a usable video file. "
            "Typical renders take 1-5 minutes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {**GENERATE_SCHEMA["properties"], **WAIT_PROPS},
        },
    },
    {
        "name": "seedance_get_video",
        "description": (
            "Check a Seedance task by ID. Returns status, progress and the video URL once "
            "the render is complete. Use this to resume a task that was submitted with "
            "wait=false or that exceeded an earlier timeout."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Task ID from seedance_generate_video."},
                "wait": {
                    "type": "boolean",
                    "default": False,
                    "description": "Keep polling until the task finishes.",
                },
                "timeout": {"type": "integer", "default": 600, "maximum": MAX_WAIT_SECONDS},
                "download": {"type": "boolean", "default": True},
                "output_path": {"type": "string"},
            },
        },
    },
    {
        "name": "seedance_download_video",
        "description": (
            "Download a Seedance video URL to a local file. Gateway URLs are short-lived, "
            "so download before the link expires."
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
        "name": "seedance_list_models",
        "description": (
            "List available Seedance models with supported resolutions, aspect ratios and "
            "reference roles. Call this when unsure which model fits the request."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

MODEL_NOTES = {
    "doubao-seedance-1-0-pro-250528": "Gen-1 pro. Stable general-purpose text-to-video.",
    "doubao-seedance-1-0-lite-t2v": "Gen-1 lite, text-to-video only. Cheapest option.",
    "doubao-seedance-1-0-lite-i2v": "Gen-1 lite, tuned for image-to-video.",
    "doubao-seedance-1-5-pro-251215": "Gen-1.5 pro. Better motion coherence than 1.0.",
    "doubao-seedance-2-0-260128": "Gen-2 flagship. Highest fidelity, slowest.",
    "doubao-seedance-2-0-fast-260128": "Gen-2 fast. Recommended default: good quality, quick.",
    "doubao-seedance-2-0-mini-260615": "Gen-2 mini. Fast and cheap, supports references.",
    "doubao-seedance-2-5-260628": "Gen-2.5. Newest; best prompt adherence.",
}


# ----------------------------------------------------------------------- tools

_client: Optional[SeedanceClient] = None


def get_client() -> SeedanceClient:
    global _client
    if _client is None:
        _client = SeedanceClient()
    return _client


def resolve_output_path(explicit: str, task_id: str) -> str:
    if explicit:
        path = os.path.abspath(os.path.expanduser(explicit))
        if os.path.isdir(path):
            return os.path.join(path, f"seedance-{task_id}.mp4")
        return path
    return os.path.join(default_output_dir(), f"seedance-{task_id}.mp4")


def maybe_download(client: SeedanceClient, result: Dict[str, Any], args: Dict[str, Any]) -> None:
    """Persist the rendered video when the caller wants a local copy."""
    if not result.get("ok") or not result.get("video_url"):
        return
    if not args.get("download", True):
        return
    dest = resolve_output_path(str(args.get("output_path") or ""), str(result.get("task_id") or "video"))
    try:
        saved = client.download(result["video_url"], dest)
        result["saved_to"] = saved["path"]
        result["size_mb"] = saved["mb"]
    except SeedanceError as exc:
        result["download_error"] = str(exc)


def tool_generate(args: Dict[str, Any]) -> Dict[str, Any]:
    client = get_client()
    created = client.create_video(
        prompt=str(args.get("prompt") or ""),
        model=str(args.get("model") or DEFAULT_MODEL),
        seconds=args.get("seconds", 5),
        resolution=str(args.get("resolution") or "720p"),
        ratio=str(args.get("ratio") or "16:9"),
        generate_audio=args.get("generate_audio"),
        references=args.get("references"),
        seed=args.get("seed"),
        camera_fixed=args.get("camera_fixed"),
        watermark=args.get("watermark"),
    )
    task_id = created["task_id"]
    log(f"submitted task {task_id} model={created.get('model')}")

    if not args.get("wait", True):
        created["next_step"] = (
            f"Task submitted. Call seedance_get_video with task_id={task_id} to check progress."
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
    url = str(args.get("url") or "")
    dest = resolve_output_path(str(args.get("output_path") or ""), "download")
    saved = client.download(url, dest)
    return {"ok": True, "saved_to": saved["path"], "size_mb": saved["mb"]}


def tool_list_models(_args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "default_model": DEFAULT_MODEL,
        "models": [{"id": m, "notes": MODEL_NOTES.get(m, "")} for m in MODELS],
        "resolutions": RESOLUTIONS,
        "ratios": RATIOS,
        "reference_roles": ROLES,
        "output_dir": default_output_dir(),
    }


HANDLERS = {
    "seedance_generate_video": tool_generate,
    "seedance_get_video": tool_get,
    "seedance_download_video": tool_download,
    "seedance_list_models": tool_list_models,
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
    is_notification = request_id is None

    if method == "initialize":
        reply(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
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
        except SeedanceError as exc:
            log(f"tool {name} failed: {exc}")
            reply(request_id, tool_result(exc.as_dict(), is_error=True))
        except Exception as exc:  # noqa: BLE001 - never kill the server on one bad call
            log(f"tool {name} crashed: {traceback.format_exc()}")
            reply(
                request_id,
                tool_result({"error": f"{type(exc).__name__}: {redact(str(exc))}"}, is_error=True),
            )
        return

    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method.startswith("resources") else "prompts"
        reply(request_id, {key: []})
        return

    if not is_notification:
        reply_error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    log(f"ready (base_url={os.environ.get('SEEDANCE_BASE_URL', 'default')})")
    if not os.environ.get("SEEDANCE_API_KEY", "").strip():
        log("WARNING: SEEDANCE_API_KEY is not set; tool calls will fail until it is provided.")

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
