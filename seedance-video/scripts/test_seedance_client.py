"""Offline tests: payload construction, validation, response parsing, polling."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seedance_client import SeedanceClient, SeedanceError, redact

def client():
    return SeedanceClient(api_key="sk-test-key-1234567890")

class TestPayload(unittest.TestCase):
    def test_text_to_video_payload(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t1", "status": "queued"}) as m:
            r = c.create_video(prompt="a cat", seconds=5, resolution="720p", ratio="16:9")
        method, path, payload = m.call_args[0]
        self.assertEqual((method, path), ("POST", "/v1/videos"))
        self.assertEqual(payload["prompt"], "a cat")
        self.assertEqual(payload["seconds"], 5)
        self.assertEqual(payload["metadata"]["resolution"], "720p")
        self.assertEqual(payload["metadata"]["ratio"], "16:9")
        self.assertEqual(r["task_id"], "t1")

    def test_references_become_content_items(self):
        c = client()
        refs = [{"url": "https://e.com/a.png", "role": "first_frame"},
                {"url": "https://e.com/b.png", "role": "last_frame"},
                {"url": "https://e.com/c.mp4", "role": "reference_video"},
                {"url": "https://e.com/d.mp3", "role": "reference_audio"}]
        with mock.patch.object(c, "_request", return_value={"id": "t2"}) as m:
            c.create_video(prompt="p", references=refs)
        content = m.call_args[0][2]["metadata"]["content"]
        self.assertEqual([i["type"] for i in content],
                         ["image_url", "image_url", "video_url", "audio_url"])
        self.assertEqual(content[0]["image_url"]["url"], "https://e.com/a.png")
        self.assertEqual(content[0]["role"], "first_frame")
        self.assertEqual(content[3]["audio_url"]["url"], "https://e.com/d.mp3")

    def test_optional_flags_only_sent_when_given(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p")
        meta = m.call_args[0][2]["metadata"]
        for absent in ("generate_audio", "seed", "camera_fixed", "watermark"):
            self.assertNotIn(absent, meta)
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="p", generate_audio=True, seed=42, camera_fixed=False, watermark=True)
        meta = m.call_args[0][2]["metadata"]
        self.assertEqual((meta["generate_audio"], meta["seed"], meta["camera_fixed"], meta["watermark"]),
                         (True, 42, False, True))

    def test_reference_only_request_needs_no_prompt(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t"}) as m:
            c.create_video(prompt="", references=[{"url": "https://e.com/a.png", "role": "first_frame"}])
        self.assertNotIn("prompt", m.call_args[0][2])

class TestValidation(unittest.TestCase):
    def test_rejects_empty_request(self):
        with self.assertRaises(SeedanceError) as e: client().create_video()
        self.assertEqual(e.exception.code, "INVALID_REQUEST")
    def test_rejects_bad_model(self):
        with self.assertRaises(SeedanceError) as e: client().create_video(prompt="p", model="gpt-4")
        self.assertEqual(e.exception.code, "INVALID_MODEL")
    def test_rejects_bad_resolution_and_ratio(self):
        for kw in ({"resolution": "8k"}, {"ratio": "5:4"}):
            with self.assertRaises(SeedanceError): client().create_video(prompt="p", **kw)
    def test_rejects_bad_reference(self):
        for bad in ([{"role": "first_frame"}], [{"url": "u", "role": "nope"}], ["notadict"]):
            with self.assertRaises(SeedanceError): client().create_video(prompt="p", references=bad)
    def test_requires_api_key(self):
        with mock.patch.dict("os.environ", {"SEEDANCE_API_KEY": ""}, clear=False):
            with self.assertRaises(SeedanceError) as e: SeedanceClient(api_key="")
            self.assertEqual(e.exception.code, "API_KEY_REQUIRED")

class TestResponses(unittest.TestCase):
    def test_url_from_openai_shape(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "id": "t", "status": "completed", "progress": 100, "metadata": {"url": "https://cdn/v.mp4"}}):
            r = c.get_video("t")
        self.assertEqual((r["video_url"], r["done"], r["ok"]), ("https://cdn/v.mp4", True, True))

    def test_url_from_native_shape(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "id": "t", "status": "succeeded", "content": {"video_url": "https://cdn/n.mp4"}}):
            r = c.get_video("t")
        self.assertEqual((r["video_url"], r["ok"]), ("https://cdn/n.mp4", True))

    def test_failed_task(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={
            "id": "t", "status": "failed", "error": {"code": "x", "message": "bad"}}):
            r = c.get_video("t")
        self.assertEqual((r["done"], r["ok"]), (True, False))
        self.assertEqual(r["error"]["code"], "x")

    def test_pending_task(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id": "t", "status": "in_progress", "progress": 40}):
            r = c.get_video("t")
        self.assertFalse(r["done"]); self.assertEqual(r["progress"], 40)

    def test_http_error_mapping(self):
        for raw, status, code, frag in [
            ('{"code":"INVALID_API_KEY","message":"Invalid API key"}', 401, "INVALID_API_KEY", "credential"),
            ('{"code":"task_not_exist","message":"no task"}', 400, "task_not_exist", "scoped"),
            ('{"error":{"message":"bad param","code":"invalid"}}', 400, "invalid", "bad param"),
        ]:
            err = SeedanceClient._http_error(raw, status)
            self.assertEqual(err.code, code)
            self.assertIn(frag, str(err))

    def test_missing_task_id_is_an_error(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"status": "queued"}):
            with self.assertRaises(SeedanceError) as e: c.create_video(prompt="p")
        self.assertEqual(e.exception.code, "BAD_RESPONSE")

class TestPolling(unittest.TestCase):
    def test_polls_until_complete(self):
        c = client()
        seq = [{"id":"t","status":"queued"},{"id":"t","status":"in_progress","progress":50},
               {"id":"t","status":"completed","metadata":{"url":"https://cdn/v.mp4"}}]
        with mock.patch.object(c, "_request", side_effect=seq), mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=60, poll_interval=1)
        self.assertTrue(r["ok"]); self.assertEqual(r["poll_attempts"], 3)

    def test_timeout_is_not_reported_as_failure_to_generate(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id":"t","status":"in_progress"}), \
             mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=2, poll_interval=1)
        self.assertTrue(r["timed_out"]); self.assertFalse(r["done"])
        self.assertIn("still running upstream", r["hint"])

    def test_stops_early_on_failure(self):
        c = client()
        with mock.patch.object(c, "_request", return_value={"id":"t","status":"failed"}), \
             mock.patch("time.sleep"):
            r = c.wait_for_video("t", timeout=60, poll_interval=1)
        self.assertEqual(r["poll_attempts"], 1); self.assertFalse(r["ok"])

class TestRedaction(unittest.TestCase):
    def test_keys_are_redacted(self):
        s = redact("failed with sk-FAKEfixture0000000000000000000000000000000000000 here")
        self.assertNotIn("FAKEfixture", s); self.assertIn("REDACTED", s)
    def test_non_key_text_untouched(self):
        self.assertEqual(redact("plain message"), "plain message")

if __name__ == "__main__":
    unittest.main(verbosity=2)
