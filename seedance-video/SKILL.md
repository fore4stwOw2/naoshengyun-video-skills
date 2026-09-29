---
name: seedance-video
description: >-
  Generate videos with Doubao Seedance through the naoshengyun gateway, from a text
  prompt or from reference images, video and audio. Use when the user asks to make,
  render or generate a video, animate a still image, produce a short clip or B-roll,
  create an image-to-video or first/last-frame transition, or check on a Seedance
  video task. Also use when asked to set up video generation in WorkBuddy, Codex or
  Claude Desktop. Do not use for editing existing video files, for still images, or
  for searching for existing stock footage.
---

# Seedance Video Generation

Generate video via an MCP server that wraps the Seedance video API. Works in any MCP
host: Tencent WorkBuddy, Codex CLI, and Claude Desktop.

## Why an MCP server

Video generation is asynchronous: submit a task, poll for status, then fetch a
temporary URL. Chat-model configuration screens (including WorkBuddy's "add model"
dialog) speak `/chat/completions` and cannot drive that flow. The MCP server absorbs
the submit/poll/download cycle and exposes it as ordinary tool calls.

## Setup

The server needs Python 3.9+ and no third-party packages.

Set two environment variables in the host's MCP configuration:

- `SEEDANCE_API_KEY` — gateway token, `sk-...` (required)
- `SEEDANCE_OUTPUT_DIR` — where videos are saved (optional, defaults to `~/Downloads/seedance`)
- `SEEDANCE_BASE_URL` — override the gateway (optional, defaults to `https://token.naoshengyun.com`)

Never paste the key into a prompt, a tracked file, or a screenshot. Keep it in the
host config only.

Host-specific configuration snippets are in `references/setup.md`. Verify a new
install with:

```bash
SEEDANCE_API_KEY=sk-... python3 scripts/verify_setup.py
```

That script checks the interpreter, TLS trust store, gateway reachability, credential
validity, and whether the video routes are deployed. Run it first whenever something
fails; it distinguishes these causes instead of reporting a generic error.

## Tools

| Tool | Purpose |
|---|---|
| `seedance_generate_video` | Submit a render; by default waits and saves the file |
| `seedance_get_video` | Check or resume a task by ID |
| `seedance_download_video` | Save a video URL to disk |
| `seedance_list_models` | List models, resolutions, ratios, reference roles |

## Usage

Text to video, the common case. `seedance_generate_video` waits for the render and
saves the file, so one call is usually enough:

```json
{"prompt": "A tabby cat stretching on a sunlit windowsill, slow dolly in, cinematic",
 "seconds": 5, "resolution": "720p", "ratio": "16:9"}
```

Animate a still image by passing it as the first frame:

```json
{"prompt": "Gentle camera push in, leaves drifting",
 "references": [{"url": "https://example.com/photo.jpg", "role": "first_frame"}]}
```

Interpolate between two stills with `first_frame` and `last_frame`. Guide style,
motion or lip sync with `reference_image`, `reference_video` and `reference_audio`.

Renders typically take 1-5 minutes. For a long or high-resolution job, submit with
`wait: false`, then poll `seedance_get_video` with the returned `task_id`. If a wait
times out the task keeps running upstream — poll the same `task_id` rather than
resubmitting, which would bill a second render.

## Choosing a model

Call `seedance_list_models` when unsure. Defaults to `doubao-seedance-2-0-fast-260128`,
which balances quality against cost and latency. Move up to `doubao-seedance-2-0-260128`
or `doubao-seedance-2-5-260628` when fidelity matters, down to
`doubao-seedance-1-0-lite-t2v` to minimise cost. Use `doubao-seedance-1-0-lite-i2v`
for image-to-video on the gen-1 line.

Cost scales with duration, resolution and model tier. Confirm with the user before
rendering anything long or at 4k, and prefer a short 720p test before a final render.

## Prompting

Name the subject, the action, the camera move, and the lighting. "Golden retriever
running through shallow surf, low tracking shot, backlit at sunset" beats "a dog at
the beach". Keep one clear action per 5-second clip; multiple scene changes in a short
clip tend to produce incoherent motion. Add `generate_audio: true` for a soundtrack.

## Handling results

Video URLs are temporary, so the tools download by default. Report the saved path to
the user. Do not paste the gateway URL into durable notes or shared documents — it
expires and may carry credentials in its signature.

## Troubleshooting

Run `scripts/verify_setup.py` first. It separates the failure modes below.

`INVALID_API_KEY` / HTTP 401 means the gateway did not recognise the credential. Check
for a truncated or stale key and confirm it has video access and remaining quota. A
valid-looking `sk-` string can still be rejected; compare against a known-bad key on
`GET /v1/models` to confirm.

HTTP 404 on `/v1/videos` means the video route is not deployed on that gateway, which
is independent of the key. Other routes such as `/v1/chat/completions` returning 401
while `/v1/videos` returns 404 confirms this. Ask the platform operator to enable the
Seedance video plugin, or point `SEEDANCE_BASE_URL` at a gateway that serves it.

`CERTIFICATE_VERIFY_FAILED` comes from python.org builds that never populated their
trust store. The client falls back to `certifi` and common system bundles
automatically; if it still fails, run `/Applications/Python 3.x/Install Certificates.command`.

`task_not_exist` means the task ID belongs to a different key. Task IDs are scoped to
the key that created them.

## Tests

```bash
python3 scripts/test_seedance_client.py
```

20 offline tests covering payload shape, validation, response parsing and polling. No
network or credential needed.

## Files

- `scripts/mcp_server.py` — MCP stdio server
- `scripts/seedance_client.py` — API client, submit/poll/download
- `scripts/verify_setup.py` — preflight diagnostic
- `references/setup.md` — WorkBuddy, Codex, Claude Desktop configuration
- `references/api.md` — endpoint and parameter reference
- `scripts/test_seedance_client.py` — offline test suite
