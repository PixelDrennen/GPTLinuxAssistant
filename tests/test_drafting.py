import io
import json
import unittest
from unittest.mock import patch

from assistant_app.drafting import complete


class DraftingTests(unittest.TestCase):
    @patch("assistant_app.drafting.loopback_opener")
    def test_question_requires_a_second_request(self, opener):
        opener.return_value.open.return_value = io.BytesIO(json.dumps({
            "response": json.dumps({"draft": "", "question": "Which scene should Rider change?"}),
        }).encode())
        result = complete("local", "Fix the scene", "Finish this prompt", [], "rider")
        self.assertEqual("", result.draft)
        self.assertEqual("Which scene should Rider change?", result.question)
        call = opener.return_value.open.call_args.args[0]
        self.assertEqual("http://127.0.0.1:11434/api/generate", call.full_url)
        self.assertIn("format", json.loads(call.data))

    @patch("assistant_app.drafting.loopback_opener")
    def test_cloud_tag_is_rejected_before_sending_context(self, opener):
        with self.assertRaises(ValueError):
            complete("model:120b-cloud", "private", "draft", [], "slack")
        opener.assert_not_called()

    @patch("assistant_app.drafting.loopback_opener")
    def test_openai_uses_explicit_key_and_structured_https_request(self, opener):
        opener.return_value.open.return_value = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": json.dumps({"draft": "Try Prefab Mode.", "question": ""})}}],
        }).encode())
        result = complete("gpt-4.1-mini", "", "How do I edit a prefab?", {}, "general", api_key="test-key")
        call = opener.return_value.open.call_args.args[0]
        payload = json.loads(call.data)
        self.assertEqual("https://api.openai.com/v1/chat/completions", call.full_url)
        self.assertEqual("Bearer test-key", call.get_header("Authorization"))
        self.assertFalse(payload["store"])
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual("Try Prefab Mode.", result.draft)

    @patch("assistant_app.drafting.loopback_opener")
    def test_image_is_attached_only_to_the_selected_provider(self, opener):
        response = json.dumps({"draft": "An inventory window.", "question": ""})
        opener.return_value.open.return_value = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": response}}],
        }).encode())
        complete("gpt-4.1-mini", "", "Look at this game", {}, "general", api_key="test-key", image=b"frame")
        payload = json.loads(opener.return_value.open.call_args.args[0].data)
        parts = payload["messages"][1]["content"]
        self.assertEqual("data:image/jpeg;base64,ZnJhbWU=", parts[1]["image_url"]["url"])
        opener.return_value.open.return_value = io.BytesIO(json.dumps({"response": response}).encode())
        complete("local-vision", "", "Look at this game", {}, "general", image=b"frame")
        call = opener.return_value.open.call_args.args[0]
        self.assertEqual("http://127.0.0.1:11434/api/generate", call.full_url)
        self.assertEqual(["ZnJhbWU="], json.loads(call.data)["images"])

    @patch("assistant_app.drafting.loopback_opener")
    def test_offline_ollama_explains_the_active_provider(self, opener):
        from urllib.error import URLError
        import errno
        opener.return_value.open.side_effect = URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        with self.assertRaisesRegex(ValueError, "Ollama is offline"):
            complete("gemma4", "", "hello", {}, "general")

    @patch("assistant_app.drafting.loopback_opener")
    def test_visual_watch_requires_a_frame_and_an_explicit_schema_result(self, opener):
        response = json.dumps({"draft": "Open the TSM ledger.", "question": "", "wait_for_view": True})
        opener.return_value.open.return_value = io.BytesIO(json.dumps({"response": response}).encode())
        reply = complete("local-vision", "", "Read my TSM ledger", {}, "general", image=b"frame",
                         may_wait=True, rechecking=True)
        request = json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertIn("wait_for_view", request["format"]["required"])
        self.assertIn("silent follow-up check", request["system"])
        self.assertTrue(reply.wait_for_view)
