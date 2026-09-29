# Instructions for AI agents

This file tells an autonomous agent how to install and operate the two video
generation skills in this repository. Follow it in order. Do not skip the
preflight step: it is the difference between a working install and a confusing
`503` later.

## What this repository provides

Two MCP stdio servers wrapping asynchronous video generation APIs:

| Directory | Models | Tool prefix |
|---|---|---|
| `seedance-video/` | Doubao Seedance, 8 models | `seedance_*` |
| `wan-video/` | Tongyi Wanxiang (Wan), 10 models | `wan_*` |

Requirements: Python 3.9 or newer. No third-party packages, no build step, no
package manager. Both servers speak MCP `2024-11-05` over stdin/stdout.

## Preferred path: run the installer

If the user has a key and the machine has network access, prefer the installer
over the manual steps. It performs every step below, refuses to overwrite an
existing host config, and — importantly — queries the gateway to find out which
models the key's group actually exposes, then configures only the skills that
key can use.

```bash
curl -fsSL https://raw.githubusercontent.com/fore4stwOw2/naoshengyun-video-skills/main/install.py -o install.py
python3 install.py --key sk-...
```

Useful flags: `--host claude|codex|workbuddy`, `--dir`, `--gateway`,
`--uninstall`. Omit `--key` to prompt for it without echoing.

Do not invent a key, and do not read one out of the user's existing config to
reuse elsewhere. If the user has no key, stop and ask for one.

The installer exits non-zero with a single-line reason on failure. If it cannot
run (no network, restricted environment, user wants manual control), fall back to
the steps below.

## Step 1: place the skill directories

Copy the directory you need to wherever the host loads skills from. For Codex
that is `~/.codex/skills/`. Other hosts only need a stable absolute path.

```bash
cp -R seedance-video ~/.codex/skills/
cp -R wan-video ~/.codex/skills/
```

## Step 2: obtain a credential and check its model group

The user must supply their own API key. This repository contains none.

Credentials are scoped to a gateway *group*, and a group exposes only a subset
of the model catalogue. A key that works for one skill may have no channel for
the other. Verify before configuring anything:

```bash
curl -s https://token.naoshengyun.com/v1/models \
  -H "Authorization: Bearer $API_KEY"
```

The returned `data[].id` values are the only models that key can use. To run
`wan-video` the list must contain a `wan*` model; for `seedance-video` it must
contain a `doubao-seedance-*` model. If the needed family is absent, stop and
tell the user their key's group lacks it. Do not retry, and do not substitute a
model from the other family.

## Step 3: run the preflight

```bash
WAN_API_KEY=$API_KEY python3 ~/.codex/skills/wan-video/scripts/verify_setup.py
SEEDANCE_API_KEY=$API_KEY python3 ~/.codex/skills/seedance-video/scripts/verify_setup.py
```

Exit code 0 means ready. Non-zero prints the specific blocking cause. The script
distinguishes interpreter version, TLS trust store, gateway reachability,
credential validity, group catalogue contents, and route deployment. Report its
output rather than guessing at a failure.

## Step 4: register the MCP server

Resolve absolute paths first. GUI hosts do not inherit a login shell, so `~` may
not expand and a bare `python3` may not resolve:

```bash
python3 -c "import sys; print(sys.executable)"
```

Codex CLI, in `~/.codex/config.toml`:

```toml
[mcp_servers.wan]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/wan-video/scripts/mcp_server.py"]
env = { WAN_API_KEY = "sk-..." }
```

Claude Desktop, in `claude_desktop_config.json`, then restart the app:

```json
{
  "mcpServers": {
    "wan": {
      "command": "/absolute/path/to/python3",
      "args": ["/absolute/path/to/wan-video/scripts/mcp_server.py"],
      "env": { "WAN_API_KEY": "sk-..." }
    }
  }
}
```

Tencent WorkBuddy: use **Connectors → Custom connector**, not Settings → Models.
The model dialog configures `/chat/completions` endpoints and cannot drive an
asynchronous video workflow.

Any other MCP host: launch `scripts/mcp_server.py` with the interpreter, pass the
key through the environment, and speak MCP over stdio.

Both servers can be registered simultaneously as separate entries.

## Step 5: call the tools

| Seedance | Wan | Purpose |
|---|---|---|
| `seedance_generate_video` | `wan_generate_video` | Generate; waits and downloads by default |
| `seedance_get_video` | `wan_get_video` | Check or resume by `task_id` |
| `seedance_download_video` | `wan_download_video` | Save a URL to disk |
| `seedance_list_models` | `wan_list_models` | Capability matrix |

`*_generate_video` completes the whole submit/poll/download cycle in one call and
returns a local file path. Renders typically take one to five minutes.

## Operating rules

**A timeout is not a failure.** If a wait expires, the task is still running
upstream. Poll `*_get_video` with the same `task_id`. Resubmitting bills a second
render.

**Respect the Wan capability matrix.** Model families differ in ways that make a
request invalid, not merely suboptimal. Only `wan2.7-i2v` supports audio-driven
lip sync. Only the wan3.0 family and `wan2.7-i2v` support a last frame. The t2v
models reject reference images entirely and require a `width*height` size such as
`1920*1080`. The client validates this locally and names the models that support
a rejected feature; surface that message instead of retrying blindly. Call
`wan_list_models` when unsure.

**Confirm cost before expensive renders.** Billing scales with duration,
resolution and model tier. Test at 720p with a short duration before a long or
high-resolution final render.

**Download promptly.** Gateway URLs are temporary; Wan returns OSS links valid
roughly 24 hours. The tools download by default. Report the saved path, not the
signed URL.

**Never expose credentials.** Keep keys in host configuration or the
environment. Do not write them into prompts, committed files, logs or
screenshots. The servers redact `sk-` patterns from their own output, but a key
pasted into a conversation is already compromised and should be rotated.

## Error handling

| Symptom | Cause | Action |
|---|---|---|
| `503 model_not_found` | Key's group has no channel for that model | Tell the user; do not retry |
| `401 INVALID_API_KEY` | Key invalid, or quota exhausted | Ask the user to check the key |
| `404` | Route not deployed at that base URL | Confirm `token.naoshengyun.com`; `api.naoshengyun.com` has no video routes |
| `task_not_exist` | Task belongs to a different key | Task IDs are key-scoped |
| `CERTIFICATE_VERIFY_FAILED` | python.org build with an empty trust store | Client auto-falls back to `certifi`; otherwise run `Install Certificates.command` |

Run `scripts/verify_setup.py` before diagnosing further. It separates these
causes; error text alone can be ambiguous.

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `SEEDANCE_API_KEY` / `WAN_API_KEY` | yes | — |
| `SEEDANCE_OUTPUT_DIR` / `WAN_OUTPUT_DIR` | no | `~/Downloads/seedance`, `~/Downloads/wan` |
| `SEEDANCE_BASE_URL` / `WAN_BASE_URL` | no | `https://token.naoshengyun.com` |

## Verifying a change

Offline test suites need no network or credential:

```bash
python3 seedance-video/scripts/test_seedance_client.py   # 20 tests
python3 wan-video/scripts/test_wan_client.py             # 40 tests
```

Run both after modifying a client or server.
