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
