"""Check benchmark fairness and timing accounting instead of asserting machine-dependent speed."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from benchmarks.benchmark_support import Timings


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkTests(unittest.TestCase):
    def test_nested_timing_does_not_count_the_same_interval_twice(self):
        readings = iter([0.0, 1.0, 3.0, 7.0])
        timings = Timings(clock=lambda: next(readings))
        with timings.measure("recording"):
            with timings.measure("screenshots"):
                pass
        # Screenshot work takes two seconds within seven seconds of recording.
        # Recording's own time is five seconds, so the categories still sum to seven.
        self.assertEqual(2.0, timings.seconds["screenshots"])
        self.assertEqual(5.0, timings.seconds["recording"])

    def test_benchmark_runs_identical_actions_and_validates_recorded_traces(self):
        with TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "benchmarks/benchmark_exploration.py"),
                 "--actions", "3", "--repeats", "1", "--warmups", "1",
                 "--widgets", "5", "--properties", "2", "--no-screenshots", "--output", directory],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            paths = list(Path(directory).glob("*/results.json"))
            self.assertEqual(1, len(paths))
            results = json.loads(paths[0].read_text(encoding="utf-8"))
            samples = results["samples"]
            self.assertEqual({"playwright_baseline", "evidence", "asm"}, {s["mode"] for s in samples})
            self.assertEqual(3, sum(not s["warmup"] for s in samples))
            self.assertEqual(3, sum(s["warmup"] for s in samples))
            first = samples[0]["action_log"]
            self.assertEqual(["click", "fill", "click"], [action["type"] for action in first])
            for sample in samples:
                self.assertEqual(first, sample["action_log"])
                seconds = sample["seconds"]
                self.assertAlmostEqual(seconds["total"], sum(v for k, v in seconds.items() if k != "total"))
                self.assertEqual(4, sample["calls"]["discovery"])
                if sample["mode"] == "playwright_baseline":
                    self.assertIsNone(sample["trace"])
                    self.assertEqual(0.0, seconds["dom_capture"])
                else:
                    self.assertEqual(3, sample["trace"]["executions"])
                    self.assertEqual(3, sample["trace"]["transitions"])
                    self.assertEqual(4, sample["trace"]["observations"])
                    self.assertEqual(0, sample["trace"]["screenshots"])
