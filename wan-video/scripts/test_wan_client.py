"""Offline tests: payload shape, capability validation, size rules, dual-surface parsing."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wan_client import WanClient, WanError, redact

def client():
    return WanClient(api_key="sk-test-key-1234567890")

def sent(m):
    return m.call_args[0][2]

class TestPayload(unittest.TestCase):
    def test_text_to_video(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t1", "status": "queued"}) as m:
            r = c.create_video(prompt="a cat", seconds=5, size="720P")
        method, path, p = m.call_args[0]
        self.assertEqual((method, path), ("POST", "/v1/videos"))
        self.assertEqual(p["model"], "wan3.0-video")
        self.assertEqual(p["prompt"], "a cat")
        self.assertEqual(p["size"], "720P")
        self.assertEqual(p["seconds"], 5)
        self.assertEqual(r["task_id"], "t1")

    def test_single_image_uses_image_field(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", image="https://e.com/a.jpg")
        p = sent(m)
        self.assertEqual(p["image"], "https://e.com/a.jpg")
        self.assertNotIn("images", p)

    def test_first_and_last_frame_use_images_array(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", image="https://e.com/a.jpg", last_frame="https://e.com/b.jpg")
        p = sent(m)
        self.assertEqual(p["images"], ["https://e.com/a.jpg", "https://e.com/b.jpg"])
        self.assertNotIn("image", p)

    def test_audio_goes_into_metadata_input(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(model="wan2.7-i2v", image="https://e.com/a.jpg",
                           audio_url="https://e.com/s.mp3")
        self.assertEqual(sent(m)["metadata"]["input"]["audio_url"], "https://e.com/s.mp3")

    def test_parameters_go_into_metadata_parameters(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", seed=42, prompt_extend=False, watermark=True, ratio="16:9")
        params = sent(m)["metadata"]["parameters"]
        self.assertEqual(params["seed"], 42)
        self.assertFalse(params["prompt_extend"])
        self.assertTrue(params["watermark"])
        self.assertEqual(params["ratio"], "16:9")

    def test_no_metadata_when_nothing_extra(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p")
        self.assertNotIn("metadata", sent(m))

    def test_explicit_media_overrides_image(self):
        c = client()
        media = [{"type": "first_frame", "url": "https://e.com/a.jpg"},
                 {"type": "driving_audio", "url": "https://e.com/s.mp3"}]
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", image="https://e.com/ignored.jpg", media=media)
        p = sent(m)
        self.assertEqual(p["metadata"]["input"]["media"], media)
        self.assertNotIn("image", p)

class TestCapabilityValidation(unittest.TestCase):
    def test_t2v_rejects_image(self):
        with self.assertRaises(WanError) as e:
            client().create_video(model="wan2.7-t2v", prompt="p", image="https://e.com/a.jpg")
        self.assertIn("text-to-video", str(e.exception))

    def test_t2v_requires_prompt(self):
        with self.assertRaises(WanError):
            client().create_video(model="wan2.7-t2v", prompt="")

    def test_last_frame_rejected_on_unsupported_model(self):
        with self.assertRaises(WanError) as e:
            client().create_video(model="wan2.2-i2v-flash", prompt="p",
                                  image="https://e.com/a.jpg", last_frame="https://e.com/b.jpg")
        msg = str(e.exception)
        self.assertIn("does not support a last frame", msg)
        self.assertIn("wan3.0-video", msg)  # names models that do

    def test_audio_only_on_wan27_i2v(self):
        with self.assertRaises(WanError) as e:
            client().create_video(model="wan3.0-video", image="https://e.com/a.jpg",
                                  audio_url="https://e.com/s.mp3")
        self.assertIn("wan2.7-i2v", str(e.exception))
        # allowed on the supporting model
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}):
            c.create_video(model="wan2.7-i2v", image="https://e.com/a.jpg",
                           audio_url="https://e.com/s.mp3")

    def test_smart_duration_only_on_wan30(self):
        with self.assertRaises(WanError) as e:
            client().create_video(model="wan2.2-i2v-plus", image="https://e.com/a.jpg", seconds=-1)
        self.assertIn("smart duration", str(e.exception))
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(model="wan3.0-video", prompt="p", seconds=-1)
        self.assertEqual(sent(m)["seconds"], -1)

    def test_last_frame_without_first_frame(self):
        with self.assertRaises(WanError) as e:
            client().create_video(prompt="p", last_frame="https://e.com/b.jpg")
        self.assertIn("needs a first frame", str(e.exception))

    def test_rejects_unknown_model_and_empty_request(self):
        with self.assertRaises(WanError) as e: client().create_video(prompt="p", model="sora")
        self.assertEqual(e.exception.code, "INVALID_MODEL")
        with self.assertRaises(WanError) as e: client().create_video()
        self.assertEqual(e.exception.code, "INVALID_REQUEST")

    def test_rejects_bad_media_entries(self):
        for bad in ([{"type": "first_frame"}], [{"type": "nope", "url": "u"}], ["str"]):
            with self.assertRaises(WanError): client().create_video(prompt="p", media=bad)

class TestSizing(unittest.TestCase):
    def test_t2v_tier_converted_to_pixels(self):
        c = client()
        for tier, px in [("480P", "854*480"), ("720P", "1280*720"), ("1080P", "1920*1080")]:
            with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
                c.create_video(model="wan2.7-t2v", prompt="p", size=tier)
            self.assertEqual(sent(m)["size"], px)

    def test_t2v_defaults_to_pixels(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(model="wan2.7-t2v", prompt="p")
        self.assertEqual(sent(m)["size"], "1920*1080")

    def test_i2v_defaults_to_tier(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", image="https://e.com/a.jpg")
        self.assertEqual(sent(m)["size"], "720P")

    def test_explicit_pixels_preserved(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", size="1920*1080")
        self.assertEqual(sent(m)["size"], "1920*1080")

    def test_resolution_kw_used_when_size_absent(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", resolution="1080p")
        self.assertEqual(sent(m)["size"], "1080P")

    def test_malformed_size_rejected(self):
        for bad in ("1920x1080", "abc", "1920*"):
            with self.assertRaises(WanError): client().create_video(prompt="p", size=bad)

class TestStatusNormalisation(unittest.TestCase):
    def test_native_uppercase_mapped(self):
        c = client()
        cases = [("PENDING", "queued", False, None), ("RUNNING", "in_progress", False, None),
                 ("SUCCEEDED", "completed", True, True), ("FAILED", "failed", True, False),
                 ("CANCELED", "cancelled", True, False)]
        for native, want, done, ok in cases:
            with mock.patch.object(c, "_request", return_value={"output": {"task_status": native, "task_id": "t"}}):
                r = c.get_video("t")
            self.assertEqual(r["status"], want)
            self.assertEqual(r["done"], done)
            if ok is not None: self.assertEqual(r["ok"], ok)

    def test_compatible_lowercase_passthrough(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t", "status": "in_progress", "progress": 60}):
            r = c.get_video("t")
        self.assertEqual((r["status"], r["done"], r["progress"]), ("in_progress", False, 60))

    def test_url_from_native_output(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "output": {"task_id": "t", "task_status": "SUCCEEDED", "video_url": "https://oss/v.mp4",
                       "actual_prompt": "rewritten"}}):
            r = c.get_video("t")
        self.assertEqual(r["video_url"], "https://oss/v.mp4")
        self.assertTrue(r["ok"])
        self.assertEqual(r["actual_prompt"], "rewritten")

    def test_url_from_compatible_metadata(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "id": "t", "status": "completed", "metadata": {"url": "https://cdn/v.mp4"}}):
            r = c.get_video("t")
        self.assertEqual(r["video_url"], "https://cdn/v.mp4")

    def test_native_task_level_error_surfaced(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "output": {"task_id": "t", "task_status": "FAILED", "code": "E1", "message": "boom"}}):
            r = c.get_video("t")
        self.assertEqual(r["error"]["code"], "E1")
        self.assertFalse(r["ok"])

class TestErrors(unittest.TestCase):
    def test_http_error_mapping(self):
        for raw, status, code, frag in [
            ('{"code":"INVALID_API_KEY","message":"Invalid API key"}', 401, "INVALID_API_KEY", "credential"),
            ('{"code":"task_not_exist","message":"no"}', 400, "task_not_exist", "scoped"),
            ('{"error":{"message":"bad size","code":"invalid"}}', 400, "invalid", "bad size"),
        ]:
            err = WanClient._http_error(raw, status)
            self.assertEqual(err.code, code)
            self.assertIn(frag, str(err))

    def test_404_explains_route_not_deployed(self):
        err = WanClient._http_error("404 page not found", 404)
        self.assertIn("not deployed", str(err))
        self.assertIn("independent of the credential", str(err))

    def test_missing_task_id(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"status": "queued"}):
            with self.assertRaises(WanError) as e: c.create_video(prompt="p")
        self.assertEqual(e.exception.code, "BAD_RESPONSE")

    def test_requires_api_key(self):
        with mock.patch.dict("os.environ", {"WAN_API_KEY": ""}, clear=False):
            with self.assertRaises(WanError) as e: WanClient(api_key="")
            self.assertEqual(e.exception.code, "API_KEY_REQUIRED")

class TestPolling(unittest.TestCase):
    def test_polls_until_complete_across_surfaces(self):
        c = client()
        seq = [{"output": {"task_id": "t", "task_status": "PENDING"}},
               {"output": {"task_id": "t", "task_status": "RUNNING"}},
               {"output": {"task_id": "t", "task_status": "SUCCEEDED", "video_url": "https://oss/v.mp4"}}]
        with mock.patch.object(c, "_request", side_effect=seq), mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=60, poll_interval=1)
        self.assertTrue(r["ok"]); self.assertEqual(r["poll_attempts"], 3)

    def test_timeout_not_reported_as_failure(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t", "status": "in_progress"}), \
             mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=2, poll_interval=1)
        self.assertTrue(r["timed_out"]); self.assertFalse(r["done"])
        self.assertIn("still running upstream", r["hint"])

    def test_stops_early_on_failure(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"output": {"task_id":"t","task_status":"FAILED"}}), \
             mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=60, poll_interval=1)
        self.assertEqual(r["poll_attempts"], 1); self.assertFalse(r["ok"])

class TestRedaction(unittest.TestCase):
    def test_key_redacted(self):
        s = redact("boom sk-FAKEfixture0000000000000000000000000000000000000 end")
        self.assertNotIn("FAKEfixture", s); self.assertIn("REDACTED", s)

class TestUrlFallback(unittest.TestCase):
    """Regression: this gateway reports completion without a URL on the
    compatible surface, so get_video must consult the native task endpoint."""

    def test_completed_without_url_falls_back_to_native(self):
        c = client()
        calls = []
        def fake(method, path, payload=None):
            calls.append(path)
            if path.startswith("/v1/videos/"):
                return {"id": "t", "status": "completed", "progress": 100}
            if path.startswith("/ali/api/v1/tasks/"):
                return {"output": {"task_id": "t", "task_status": "SUCCEEDED",
                                   "video_url": "https://oss/v.mp4", "actual_prompt": "rw"}}
            raise AssertionError(path)
        with mock.patch.object(c, "_request", side_effect=fake):
            r = c.get_video("t")
        self.assertEqual(r["video_url"], "https://oss/v.mp4")
        self.assertEqual(r["actual_prompt"], "rw")
        self.assertTrue(r["ok"])
        self.assertEqual(len(calls), 2, "should consult the native endpoint exactly once")

    def test_no_native_call_when_url_already_present(self):
        c = client()
        calls = []
        def fake(method, path, payload=None):
            calls.append(path)
            return {"id": "t", "status": "completed", "metadata": {"url": "https://cdn/v.mp4"}}
        with mock.patch.object(c, "_request", side_effect=fake):
            r = c.get_video("t")
        self.assertEqual(r["video_url"], "https://cdn/v.mp4")
        self.assertEqual(len(calls), 1, "must not call the native endpoint unnecessarily")

    def test_no_native_call_while_still_running(self):
        c = client()
        calls = []
        with mock.patch.object(c, "_request", side_effect=lambda m, p, pl=None: (
                calls.append(p), {"id": "t", "status": "in_progress"})[1]):
            c.get_video("t")
        self.assertEqual(len(calls), 1)

    def test_native_failure_does_not_break_result(self):
        c = client()
        def fake(method, path, payload=None):
            if path.startswith("/ali/"):
                raise WanError("native down", code="NETWORK_ERROR")
            return {"id": "t", "status": "completed"}
        with mock.patch.object(c, "_request", side_effect=fake):
            r = c.get_video("t")
        self.assertTrue(r["ok"])
        self.assertNotIn("video_url", r)

    def test_content_endpoint_url(self):
        self.assertEqual(client().content_url("T"),
                         "https://token.naoshengyun.com/v1/videos/T/content")

    def test_content_download_is_authenticated(self):
        c = client()
        with mock.patch.object(c, "_download", return_value={"path": "/tmp/x.mp4", "bytes": 10, "mb": 0.0}) as m:
            c.download_task_content("T", "/tmp/x.mp4")
        self.assertTrue(m.call_args.kwargs.get("authenticated"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
