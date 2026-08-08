from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.tavily import (
    TavilyConfigurationError,
    resolve_credential_source,
    TavilyClient,
    tavily_api_key,
    web_search_config_path,
)


class TavilyCredentialTests(unittest.TestCase):
    def test_config_path_precedence(self) -> None:
        self.assertEqual(
            web_search_config_path({"PI_CODING_AGENT_DIR": "/agent", "XDG_CONFIG_HOME": "/xdg", "HOME": "/home"}),
            Path("/agent/web-search.json"),
        )
        self.assertEqual(
            web_search_config_path({"XDG_CONFIG_HOME": "/xdg", "HOME": "/home"}),
            Path("/xdg/pi/web-search.json"),
        )
        self.assertEqual(web_search_config_path({"HOME": "/home"}), Path("/home/.pi/web-search.json"))

    def test_literal_environment_and_escaped_sources(self) -> None:
        env = {"TAVILY_API_KEY": "environment", "NAMED": "named"}
        self.assertEqual(resolve_credential_source("literal", env["TAVILY_API_KEY"], environment=env), "environment")
        self.assertEqual(resolve_credential_source("$NAMED", "environment", environment=env), "named")
        self.assertEqual(resolve_credential_source("${NAMED}", "environment", environment=env), "named")
        self.assertEqual(resolve_credential_source("$$literal", "environment", environment=env), "$literal")
        self.assertEqual(resolve_credential_source("$!literal", "environment", environment=env), "!literal")

    def test_command_source_uses_trimmed_output(self) -> None:
        completed = subprocess.CompletedProcess("command", 0, b" secret\n", b"")
        with patch("open_law_lens.tavily.subprocess.run", return_value=completed) as run:
            value = resolve_credential_source("!trusted command", environment={"HOME": "/safe", "SECRET": "omit"})
        self.assertEqual(value, "secret")
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertNotIn("SECRET", run.call_args.kwargs["env"])

    def test_malformed_timeout_and_output_bound_errors_are_redacted(self) -> None:
        with self.assertRaisesRegex(TavilyConfigurationError, "invalid-source"):
            resolve_credential_source("$BAD-NAME", environment={})
        with patch("open_law_lens.tavily.subprocess.run", side_effect=subprocess.TimeoutExpired("secret-command", 5)):
            with self.assertRaisesRegex(TavilyConfigurationError, "command-timeout") as caught:
                resolve_credential_source("!secret-command", environment={})
        self.assertNotIn("secret-command", str(caught.exception))
        completed = subprocess.CompletedProcess("command", 0, b"x" * 16_385, b"")
        with patch("open_law_lens.tavily.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(TavilyConfigurationError, "output-too-large"):
                resolve_credential_source("!command", environment={})

    def test_request_shape_and_result_deduplication(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return json.dumps({
                    "answer": "ignored",
                    "results": [
                        {"url": "https://EXAMPLE.com/case#one", "title": "First", "content": "lead", "raw_content": "body"},
                        {"url": "https://example.com/case#two", "title": "Duplicate"},
                    ],
                }).encode()

        with patch("open_law_lens.tavily.urllib.request.urlopen", return_value=Response()) as urlopen:
            results = TavilyClient("test-key").search("  case   query ")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["query"], "case query")
        self.assertEqual(body["search_depth"], "basic")
        self.assertEqual(body["max_results"], 10)
        self.assertEqual(body["include_raw_content"], "markdown")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].raw_content, "body")

    def test_loads_pi_config_and_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "web-search.json"
            path.write_text(json.dumps({"tavilyApiKey": "literal"}), encoding="utf-8")
            env = {"PI_CODING_AGENT_DIR": temp_dir, "TAVILY_API_KEY": "environment"}
            self.assertEqual(tavily_api_key(env), "environment")


if __name__ == "__main__":
    unittest.main()
