"""Smoke-test the shared launcher without upstream services or V8."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class StartTest(unittest.TestCase):
    def test_external_modules_arguments_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "mcp-v8"
            executable.write_text(
                '#!/bin/bash\nprintf "%s\\n" "$@" > "$TEST_ARGS"\nexit 7\n'
            )
            executable.chmod(0o755)
            output = root / "arguments"
            env = dict(os.environ, PATH=directory + ":" + os.environ["PATH"],
                       TEST_ARGS=str(output), BROWSER_MCP_ADDR="127.0.0.1:1",
                       EXEC_MCP_ADDR="127.0.0.1:1", BROWSER_MCP_WAIT_SECONDS="0",
                       EXEC_MCP_WAIT_SECONDS="0")
            result = subprocess.run(
                ["bash", str(Path(__file__).with_name("start.sh")),
                 "--http-port", "8080"],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(output.read_text().splitlines(),
                             ["--allow-external-modules", "--http-port", "8080"])


if __name__ == "__main__":
    unittest.main()
