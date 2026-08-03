import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import main


MENU_DATA = {
    "title": "8월 3일 ~ 8월 7일 식단표",
    "weekly_menu": [
        {
            "day_of_week": "월",
            "date": "2026-08-03",
            "main_menus": ["백미밥", "순두부찌개", "치킨까스&머스타드"],
            "side_menus": ["샐러드우동", "삼색콩자반", "다시마채무침", "배추김치"],
            "calories": 1160,
        }
    ],
}


def completed_response(data=MENU_DATA):
    response = Mock()
    response.json.return_value = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(data, ensure_ascii=False)}
                ],
            }
        ],
    }
    return response


class OpenAiOcrTest(unittest.TestCase):
    def setUp(self):
        print_patch = patch("builtins.print")
        print_patch.start()
        self.addCleanup(print_patch.stop)

    def write_png_named_jpg(self):
        image = tempfile.NamedTemporaryFile(suffix=".jpg")
        image.write(b"\x89PNG\r\n\x1a\nfixture")
        image.flush()
        self.addCleanup(image.close)
        return image.name

    @patch("main.requests.post")
    def test_loads_api_key_from_dotenv_when_environment_is_missing(self, post):
        post.return_value = completed_response()
        env_file = tempfile.NamedTemporaryFile(mode="w", suffix=".env", encoding="utf-8")
        env_file.write('OPENAI_API_KEY="file-key"\n')
        env_file.flush()
        self.addCleanup(env_file.close)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(main, "ENV_FILE", Path(env_file.name), create=True),
        ):
            result = main.run_openai_ocr(self.write_png_named_jpg())

        self.assertEqual(result, MENU_DATA)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer file-key",
        )

    @patch("main.requests.post")
    def test_sends_png_with_strict_schema_and_returns_existing_contract(self, post):
        post.return_value = completed_response()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            result = main.run_openai_ocr(self.write_png_named_jpg())

        self.assertEqual(result, MENU_DATA)
        post.return_value.raise_for_status.assert_called_once_with()
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["timeout"], 120)
        self.assertEqual(kwargs["json"]["model"], "gpt-4o-mini")
        self.assertFalse(kwargs["json"]["store"])
        image_input = kwargs["json"]["input"][0]["content"][1]
        self.assertEqual(image_input["detail"], "high")
        self.assertTrue(image_input["image_url"].startswith("data:image/png;base64,"))
        output_format = kwargs["json"]["text"]["format"]
        self.assertTrue(output_format["strict"])
        self.assertEqual(
            output_format["schema"]["required"],
            ["title", "weekly_menu"],
        )

    @patch("main.requests.post")
    def test_returns_none_for_refusal_incomplete_and_timeout(self, post):
        refusal = completed_response()
        refusal.json.return_value["output"][0]["content"] = [
            {"type": "output_text", "text": json.dumps(MENU_DATA)},
            {"type": "refusal", "refusal": "request refused"},
        ]
        incomplete = completed_response()
        incomplete.json.return_value = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }

        for failure in (refusal, incomplete, requests.Timeout("timed out")):
            with self.subTest(failure=failure), patch.dict(
                os.environ, {"OPENAI_API_KEY": "test-key"}
            ):
                if isinstance(failure, Exception):
                    post.side_effect = failure
                    post.return_value = None
                else:
                    post.side_effect = None
                    post.return_value = failure

                self.assertIsNone(main.run_openai_ocr(self.write_png_named_jpg()))

    @patch("main.requests.post")
    def test_missing_key_or_unsupported_image_does_not_call_api(self, post):
        with tempfile.TemporaryDirectory() as directory:
            missing_env_file = Path(directory) / ".env"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(main, "ENV_FILE", missing_env_file, create=True),
            ):
                self.assertIsNone(main.run_openai_ocr("missing.jpg"))
        post.assert_not_called()

        image = tempfile.NamedTemporaryFile(suffix=".jpg")
        image.write(b"not-an-image")
        image.flush()
        self.addCleanup(image.close)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            self.assertIsNone(main.run_openai_ocr(image.name))
        post.assert_not_called()

        oversized = tempfile.NamedTemporaryFile(suffix=".png")
        oversized.write(b"\x89PNG\r\n\x1a\n" + b"x" * (main.MAX_IMAGE_BYTES + 1))
        oversized.flush()
        self.addCleanup(oversized.close)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            self.assertIsNone(main.run_openai_ocr(oversized.name))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
