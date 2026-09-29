---
name: wan-video
description: >-
  Generate videos with Wan (Tongyi Wanxiang, wan3.0 and earlier) through the
  naoshengyun gateway, from a text prompt, a reference image, a first/last frame pair,
  or driving audio for lip sync. Use when the user asks to make, render or generate a
  video, animate a still image, produce a short clip or B-roll, interpolate between two
  images, or check on a Wan video task. Also use when asked to set up Wan video
  generation in WorkBuddy, Codex or Claude Desktop. Do not use for editing existing
  video files, for still images, or for searching for existing stock footage.
---

# Wan Video Generation

Generate video via an MCP server that wraps the Wan video API. Works in any MCP host:
Tencent WorkBuddy, Codex CLI, and Claude Desktop.

## Why an MCP server

Video generation is asynchronous: submit a task, poll for status, then fetch a
temporary URL. Chat-model configuration screens (including WorkBuddy's "add model"
dialog) speak `/chat/completions` and cannot drive that flow. The MCP server absorbs
the submit/poll/download cycle and exposes it as ordinary tool calls.

## Setup

Needs Python 3.9+ and no third-party packages.

Environment variables in the host's MCP configuration:

- `WAN_API_KEY` — gateway token, `sk-...` (required)
- `WAN_OUTPUT_DIR` — where videos are saved (optional, defaults to `~/Downloads/wan`)
- `WAN_BASE_URL` — override the gateway (optional, defaults to `https://token.naoshengyun.com`)

Never paste the key into a prompt, a tracked file, or a screenshot. Keep it in the
host config only.

Host-specific snippets are in `references/setup.md`. Verify an install with:

```bash
WAN_API_KEY=sk-... python3 scripts/verify_setup.py
```

That script checks the interpreter, TLS trust store, gateway reachability, credential
validity, and whether the video routes are deployed. Run it first whenever something
fails; it distinguishes these causes instead of reporting a generic error.

## Tools

| Tool | Purpose |
|---|---|
| `wan_generate_video` | Submit a render; by default waits and saves the file |
| `wan_get_video` | Check or resume a task by ID |
| `wan_download_video` | Save a video URL to disk |
| `wan_list_models` | Model capability matrix |

## Usage

Text to video. `wan_generate_video` waits for the render and saves the file, so one
call is usually enough:

```json
{"prompt": "A tabby cat running through a sunlit meadow, cinematic", "seconds": 5}
```

Animate a still image:

```json
{"prompt": "Gentle camera push in, leaves drifting",
 "image": "https://example.com/photo.jpg"}
```

Interpolate between two stills. Needs a model with last-frame support:

```json
{"model": "wan3.0-video", "prompt": "Smooth transition from dawn to dusk",
 "image": "https://example.com/first.jpg",
 "last_frame": "https://example.com/last.jpg"}
```

Lip sync from driving audio, `wan2.7-i2v` only:

```json
{"model": "wan2.7-i2v", "image": "https://example.com/portrait.jpg",
 "audio_url": "https://example.com/speech.mp3"}
```

Renders typically take 1-5 minutes. For a long or high-resolution job, submit with
`wait: false`, then poll `wan_get_video` with the returned `task_id`. If a wait times
out the task keeps running upstream — poll the same `task_id` rather than resubmitting,
which would bill a second render.

## Choosing a model

Capabilities differ in ways that change what a request may contain, so call
`wan_list_models` when a request needs a specific feature. Key constraints:

- `wan3.0-video` (default) and `wan3.0-video-prime` handle both text-to-video and
  image-to-video, support a last frame, and accept `seconds: -1` for smart duration.
- `wan2.7-i2v` is the only model with audio-driven lip sync. It also supports a last frame.
- `wan2.7-t2v` and `wan2.5-t2v-preview` are text-only. They reject reference images and
  require a `width*height` size; the client substitutes `1920*1080` if given a tier.
- `wan2.2-*` and `wanx2.1-*` are image-to-video without last-frame support. The `flash`
  and `turbo` tiers are the cheapest options.

The client validates these combinations before calling the gateway, so an unsupported
pairing returns a message naming the models that do support the feature.

## Sizing

`size` takes either explicit pixels (`1920*1080`) or a tier (`480P`, `720P`, `1080P`).
Text-to-video models require pixels and default to `1920*1080`; image-to-video defaults
to `720P`. Cost scales with duration, resolution and model tier, so confirm before
rendering anything long or at 1080P, and prefer a short 720P test first.

## Prompting

Name the subject, the action, the camera move, and the lighting. "Golden retriever
running through shallow surf, low tracking shot, backlit at sunset" beats "a dog at the
beach". Keep one clear action per 5-second clip. The service rewrites prompts by
default, which usually helps; pass `prompt_extend: false` to use the prompt verbatim.
When rewriting is on, the response includes `actual_prompt` showing what was used.

## Handling results

Wan returns OSS links that expire after about 24 hours, so the tools download by
default. Report the saved path to the user. Keep the gateway URL out of durable notes
and shared documents.

On this gateway the OpenAI-compatible poll reports `completed` without a URL. The
client handles that automatically: when a task finishes with no URL it consults the
native task endpoint for `output.video_url`, and can stream the file from
`/v1/videos/{id}/content` as a last resort. Nothing extra is required from the caller.

## Troubleshooting

Run `scripts/verify_setup.py` first. It separates the failure modes below.

`INVALID_API_KEY` / HTTP 401 means the gateway did not recognise the credential. Check
for a truncated or stale key and confirm it has video access and remaining quota. A
valid-looking `sk-` string can still be rejected; compare against a known-bad key on
`GET /v1/models` to confirm.

HTTP 404 on `/v1/videos` means the video route is not deployed on that gateway, which
is independent of the key. Other routes such as `/v1/chat/completions` returning 401
while `/v1/videos` returns 404 confirms this. Ask the platform operator to enable the
Wan video plugin, or point `WAN_BASE_URL` at a gateway that serves it.

`CERTIFICATE_VERIFY_FAILED` comes from python.org builds that never populated their
trust store. The client falls back to `certifi` and common system bundles
automatically; if it still fails, run `/Applications/Python 3.x/Install Certificates.command`.

`task_not_exist` means the task ID belongs to a different key. Task IDs are scoped to
the key that created them.

## Tests

```bash
python3 scripts/test_wan_client.py
```

40 offline tests covering payload shape, the model capability matrix, size rules,
status normalisation across both gateway surfaces, and the URL fallback above. No
network or credential needed.

## Files

- `scripts/mcp_server.py` — MCP stdio server
- `scripts/wan_client.py` — API client, submit/poll/download
- `scripts/verify_setup.py` — preflight diagnostic
- `references/setup.md` — WorkBuddy, Codex, Claude Desktop configuration
- `references/api.md` — endpoint and parameter reference
- `scripts/test_wan_client.py` — offline test suite
