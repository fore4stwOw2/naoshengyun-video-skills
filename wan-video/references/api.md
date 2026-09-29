# Wan video API reference

Base URL: `https://token.naoshengyun.com` (override with `WAN_BASE_URL`).
Auth: `Authorization: Bearer <WAN_API_KEY>` on every request.

Two equivalent surfaces exist. This skill uses the OpenAI-compatible one; the native
Alibaba passthrough is documented for reference.

## OpenAI-compatible (used by this skill)

### POST /v1/videos

Create an async task.

| Field | Type | Notes |
|---|---|---|
| `model` | string | Required. See model table below. |
| `prompt` | string | Required for t2v; optional when an image is supplied. |
| `image` | uri | First frame for image-to-video. Highest priority. |
| `images` | uri[] | First and second entries become first and last frame. |
| `input_reference` | uri | Legacy alias, lower priority than `image`/`images`. |
| `size` | string | `width*height` such as `1920*1080`, or a tier `480P`/`720P`/`1080P`. t2v requires pixels. |
| `seconds` | integer | Duration, default 5. `-1` means smart duration (wan3.0 only). |
| `metadata` | object | Passthrough, see below. |

`metadata.input` merges into the upstream input:

| Field | Notes |
|---|---|
| `media` | Explicit media array; when present, `image`/`images` are not consulted |
| `audio_url` | Driving audio, `wan2.7-i2v` only; becomes a `driving_audio` media item |

A `media` item is `{type, url}` where type is one of `first_frame`, `last_frame`,
`driving_audio`, `reference_video`, `reference_image`, `reference_audio`, `file`,
`link`, `first_clip`.

`metadata.parameters` merges into upstream parameters: `prompt_extend` (default true),
`watermark` (default off), `seed`, `ratio` (wan3.0 defaults to `adaptive`),
`resolution`, `size`, `duration`.

Response: `{id, object, model, status, progress, created_at}`. Keep `id`; it is the task
handle. `task_id` is a deprecated alias.

Example:

```json
{
  "model": "wan3.0-video",
  "prompt": "A tabby cat running through a sunlit meadow, cinematic",
  "seconds": 5,
  "size": "720P",
  "metadata": {"parameters": {"prompt_extend": true, "seed": 42}}
}
```

### GET /v1/videos/{task_id}

Poll a task. Status is `queued`, `in_progress`, `completed`, `failed` or `unknown`,
plus `progress` 0-100. Failures carry `error.code` and `error.message`.

Task IDs are scoped to the creating key; another key gets HTTP 400 `task_not_exist`.

Observed behaviour on this gateway: the compatible poll returns `status: completed`
with no URL field at all. Two other sources carry the video:

- `GET /ali/api/v1/tasks/{task_id}` returns `output.video_url` (an Alibaba OSS link).
- `GET /v1/videos/{task_id}/content` streams the MP4 bytes directly and requires the
  `Authorization` header.

The client tries the compatible surface, falls back to the native endpoint, and can
stream from the content endpoint, so callers always get a file.

## Native Alibaba passthrough

`POST /ali/api/v1/services/aigc/video-generation/video-synthesis` and
`GET /ali/api/v1/tasks/{task_id}` mirror the DashScope wire format, with `task_id`
rewritten to the platform task ID.

The native response differs from the compatible surface in two ways that matter:

- Status lives at `output.task_status` and is uppercase: `PENDING`, `RUNNING`,
  `SUCCEEDED`, `FAILED`, `CANCELED`, `UNKNOWN`.
- The video URL lives at `output.video_url`, not `metadata.url`.

The client normalises both, so either surface yields the same lowercase status and a
single `video_url` field. `output.actual_prompt` shows the rewritten prompt when
`prompt_extend` is on.

## Models

| Model | i2v | Last frame | Audio | Smart duration | Notes |
|---|---|---|---|---|---|
| `wan3.0-video` | yes | yes | no | yes | Gen-3 flagship, recommended default |
| `wan3.0-video-prime` | yes | yes | no | yes | Highest fidelity, slowest |
| `wan2.7-i2v` | yes | yes | yes | no | Only model with lip sync |
| `wan2.7-t2v` | no | no | no | no | Text only, needs `width*height` |
| `wan2.5-t2v-preview` | no | no | no | no | Text only, needs `width*height` |
| `wan2.5-i2v-preview` | yes | no | no | no | Gen-2.5 image-to-video |
| `wan2.2-i2v-flash` | yes | no | no | no | Cheapest and fastest |
| `wan2.2-i2v-plus` | yes | no | no | no | Better quality than flash |
| `wanx2.1-i2v-plus` | yes | no | no | no | Legacy quality tier |
| `wanx2.1-i2v-turbo` | yes | no | no | no | Legacy fast tier |

Cost scales with duration, resolution and tier. Test at 720P before a 1080P final.

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

Wan returns Alibaba OSS links that expire after about 24 hours. Download promptly, and
keep them out of durable notes, shared docs and screenshots.
