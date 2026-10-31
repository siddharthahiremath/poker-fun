import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class ArenaTests(unittest.TestCase):
    def run_arena(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "bench/arena.py"), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )

    def test_exact_count_and_duplicate_names(self):
        result = self.run_arena(
            "--games", "7", "--procs", "3", "--time", "0.001",
            "--seed", "42", "--diagnostics", "--json",
            str(ROOT / "bench/bots/allin.py"), str(ROOT / "bench/bots/allin.py"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["games"], 7)
        self.assertEqual(sum(report["wins"].values()), 7)
        self.assertEqual(set(report["actions"]), {"allin-0", "allin-1"})
        self.assertEqual(report["notes"], {})

    def test_failed_agent_aborts_benchmark(self):
        result = self.run_arena(
            "--games", "1", "--procs", "1", "--json",
            str(ROOT / "bench/nonexistent_agent.py"), str(ROOT / "bench/bots/allin.py"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to score a broken lineup", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_zero_games_rejected(self):
        result = self.run_arena(
            "--games", "0", str(ROOT / "bench/bots/allin.py"),
            str(ROOT / "bench/bots/allin.py"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Need positive", result.stderr)


if __name__ == "__main__":
    unittest.main()
