#!/usr/bin/env python3
"""Tests for token handling in authentik_blueprint_sync."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "authentik_blueprint_sync.py"


class PublicCliTokenFileTests(unittest.TestCase):
    def test_token_file_is_required_for_every_command(self):
        for command in ("export", "apply"):
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT_PATH), command],
                    cwd=REPO_ROOT,
                    env={"HOME": "/nonexistent", "PATH": ""},
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("the following arguments are required: --token-file", result.stderr)


if __name__ == "__main__":
    unittest.main()
