# Seedance video API reference

Base URL: `https://token.naoshengyun.com` (override with `SEEDANCE_BASE_URL`).
Auth: `Authorization: Bearer <SEEDANCE_API_KEY>` on every request.

The gateway exposes two equivalent surfaces. This skill uses the OpenAI-compatible
one; the native Ark passthrough is documented for reference.

## OpenAI-compatible (used by this skill)

### POST /v1/videos

Create an async task.

| Field | Type | Notes |
|---|---|---|
| `model` | string | Required. See model list below. |
| `prompt` | string | Required for text-to-video; optional when references are supplied. |
| `seconds` | integer | Duration. `-1` lets the model choose. Max 3600. |
| `metadata` | object | Generation options, below. |

`metadata` fields:

| Field | Type | Notes |
|---|---|---|
| `resolution` | enum | `480p`, `720p`, `1080p`, `4k` |
| `ratio` | enum | `adaptive`, `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9` |
| `content` | array | Reference items; see below |
| `generate_audio` | boolean | Generate a soundtrack |
| `seed` | integer | Reproducible output |
| `camera_fixed` | boolean | Lock the camera |
| `watermark` | boolean | Add an AI watermark |
| `frames` | integer | Frame count; duration is estimated as `floor(frames/24)` if `seconds` is absent |
| `return_last_frame` | boolean | Also return the final frame |
| `output_format` | enum | `mp4`, `mov` |

A `content` item has `type` (`text`, `image_url`, `video_url`, `audio_url`,
`draft_task`), the matching URL object, and a `role`: `first_frame`, `last_frame`,
`reference_image`, `reference_video`, `reference_audio`. URLs may be public https,
data URLs, or `asset://` IDs. Top-level `prompt` is appended as the final text item,
so text items inside `content` are dropped.

Response: `{id, object, model, status, progress, created_at}`. Keep `id`; it is the
task handle. `task_id` is a deprecated alias.

Example:

```json
{
  "model": "doubao-seedance-2-0-fast-260128",
  "prompt": "A tabby cat stretching on a sunlit windowsill, cinematic",
  "seconds": 5,
  "metadata": {"resolution": "720p", "ratio": "16:9", "generate_audio": true}
}
```

### GET /v1/videos/{task_id}

Poll a task. Status is one of `queued`, `in_progress`, `completed`, `failed`,
`unknown`, plus `progress` 0-100. On success the URL is at `metadata.url`. On failure
`error.code` and `error.message` explain why. `usage` carries upstream billing.

Task IDs are scoped to the creating key; another key gets HTTP 400 `task_not_exist`.

## Native Ark passthrough

`POST /doubao/api/v3/contents/generations/tasks` and
`GET /doubao/api/v3/contents/generations/tasks/{task_id}` mirror Volcengine Ark's wire
format, with `id` rewritten to the platform task ID. Native status values are
`queued`, `running`, `succeeded`, `failed`, and the URL is at `content.video_url` with
`content.last_frame_url` alongside. Use this only if you need an Ark-specific field.

## Models

| Model | Notes |
|---|---|
| `doubao-seedance-1-0-pro-250528` | Gen-1 pro, stable general purpose |
| `doubao-seedance-1-0-lite-t2v` | Gen-1 lite, text-to-video only, cheapest |
| `doubao-seedance-1-0-lite-i2v` | Gen-1 lite, tuned for image-to-video |
| `doubao-seedance-1-5-pro-251215` | Gen-1.5 pro, better motion coherence |
| `doubao-seedance-2-0-260128` | Gen-2 flagship, highest fidelity, slowest |
| `doubao-seedance-2-0-fast-260128` | Gen-2 fast, recommended default |
| `doubao-seedance-2-0-mini-260615` | Gen-2 mini, fast and cheap, supports references |
| `doubao-seedance-2-5-260628` | Gen-2.5, newest, best prompt adherence |

Cost scales with duration, resolution and tier. Test at 720p before a 4k final.

## Errors

| HTTP | Code | Meaning |
|---|---|---|
| 400 | validation | Bad parameters; the message names the field |
| 400 | `task_not_exist` | Unknown task for this key |
| 401 | `API_KEY_REQUIRED` | No credential sent |
| 401 | `INVALID_API_KEY` | Credential not recognised, or out of quota |
| 404 | — | Route not deployed on this gateway; not a credential problem |

Distinguishing 401 from 404 matters. 401 means the request reached the auth layer, so
the route exists and the key is at fault. 404 on `/v1/videos` while
`/v1/chat/completions` returns 401 means the video plugin is not enabled on that
gateway, and no key will fix it.

## Video URLs

Generated URLs are temporary and may carry signed credentials. Download promptly, and
keep them out of durable notes, shared docs and screenshots.
