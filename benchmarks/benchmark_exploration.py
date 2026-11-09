"""Compare an X-action Playwright baseline script, evidence recording, and ASM exploration."""

import argparse
from datetime import datetime
from importlib.metadata import version
import json
from pathlib import Path
import platform
from statistics import median
from time import perf_counter
from uuid import uuid4

from playwright.sync_api import sync_playwright
from testar_evidence import EvidenceReader
from testar_evidence_playwright import CaptureOptions, PlaywrightEvidence
from testar_state_model_asm_playwright import (
    ActionDerivationOptions, PlaywrightExploration, PlaywrightExplorationDriver, default_configuration, derive_actions,
)

from benchmark_support import LocalFixture, PHASES, Timings, recording_timings


MODES = ("playwright_baseline", "evidence", "asm")


def require_one_action(actions):
    """The fixture offers one choice, making all modes follow the same execution path."""
    if len(actions) != 1:
        raise RuntimeError(f"The benchmark requires one eligible action, found {len(actions)}")
    return actions[0]


def validate_trace(directory, action_count, screenshots):
    """Check correctness outside the measured interval rather than timing the reader."""
    evidence = EvidenceReader.read(directory)
    if len(evidence.action_executions) != action_count:
        raise RuntimeError("The trace did not record exactly the requested action count")
    if any(record["status"] != "completed" for record in evidence.action_executions.values()):
        raise RuntimeError("The benchmark recorded a non-completed execution")
    if len(evidence.recorded_transitions) != action_count or len(evidence.observations) != action_count + 1:
        raise RuntimeError("The trace did not preserve one connected result per action")
    screenshot_count = sum(artifact["media_type"] == "image/png"
                           for observation in evidence.observations.values()
                           for artifact in observation["artifacts"])
    if screenshot_count != (action_count + 1 if screenshots else 0):
        raise RuntimeError("The trace screenshot count did not match its capture configuration")
    return {
        "screenshots": screenshot_count,
        "observations": len(evidence.observations),
        "executions": len(evidence.action_executions),
        "transitions": len(evidence.recorded_transitions),
        "jsonl_bytes": (directory / "evidence.jsonl").stat().st_size,
    }


def run_sample(browser, url, mode, arguments, output):
    """Execute one fresh-browser-context sample; no timing hooks remain afterwards."""
    timings = Timings()
    action_derivation_options = ActionDerivationOptions(input_values={"#entry": "benchmark text"})
    timed_derive_actions = timings.wrap("action_derivation", derive_actions)
    ready = timings.wrap("readiness", lambda page: page.wait_for_load_state("domcontentloaded"))
    recorder = None
    exploration = None
    driver = None
    started = perf_counter()
    with timings.measure("startup"):
        context = browser.new_context()
    try:
        with timings.measure("startup"):
            page = context.new_page()
            page.goto(url)
            if mode != "playwright_baseline":
                recorder = PlaywrightEvidence.start_trace(
                    output, page, sut="benchmark", test_objective=mode,
                    options=CaptureOptions(screenshots=not arguments.no_screenshots,
                                           max_widgets=min(5000, arguments.widgets * 2 + 64)))
        if mode == "asm":
            with timings.measure("model_setup"):
                exploration = PlaywrightExploration(
                    page, default_configuration(arguments.actions), recorder=recorder,
                    historical_traces=arguments.existing_trace, action_derivation_options=action_derivation_options,
                    derive_actions=timed_derive_actions, wait_until_ready=ready, choose_index=lambda size: 0,
                    state_without_actions="stop")
                driver = exploration.driver
        elif mode == "evidence":
            with timings.measure("startup"):
                driver = PlaywrightExplorationDriver(
                    page, recorder, action_derivation_options=action_derivation_options,
                    derive_actions=timed_derive_actions, wait_until_ready=ready, state_without_actions="stop")
        with recording_timings(timings, page, recorder, exploration.asm if exploration else None, driver) as actions:
            if mode == "playwright_baseline":
                # This benchmark script controls X actions (--actions). At each step
                # it takes the fixture's only eligible action and asks Playwright to
                # execute it. No ASM, state model, or evidence recorder is created.
                ready(page)
                available = timed_derive_actions(page, action_derivation_options)
                for _ in range(arguments.actions):
                    action = require_one_action(available)
                    if not action.applicable():
                        raise RuntimeError("The fixture's next action is not applicable")
                    action.execute(5000)
                    ready(page)
                    # Include result-state action derivation, just as the recording driver does.
                    available = timed_derive_actions(page, action_derivation_options)
            elif mode == "evidence":
                # The benchmark again takes the only choice. The driver additionally
                # records states, available actions, executions, and results; no ASM runs.
                for _ in range(arguments.actions):
                    observation = driver.observe()
                    choice = require_one_action(observation.context["choices"])
                    selection = {"choice_id": choice["choice_id"]}
                    execution = driver.prepare_execution(selection)
                    if execution is None:
                        raise RuntimeError("The fixture unexpectedly needed a refreshed observation")
                    driver.execute(selection, execution)
            else:
                # Here the real ASM loop updates its model and selects each action.
                with timings.measure("coordination"):
                    result = exploration.run()
                if result.stopped.get("reason") != "action_limit_reached":
                    raise RuntimeError("ASM exploration stopped before reaching the requested action count")
            # These checks are outside timing categories but inside total, so they
            # appear as unclassified overhead rather than being attributed to an ASM.
            final_step = page.evaluate("() => window.benchmarkStep")
            action_log = list(actions)
        if final_step != arguments.actions or len(action_log) != arguments.actions:
            raise RuntimeError("The fixture execution did not match the requested action count")
    finally:
        with timings.measure("cleanup"):
            try:
                if recorder is not None:
                    recorder.close()
            finally:
                context.close()
    elapsed = perf_counter() - started
    phases = {phase: timings.seconds[phase] for phase in PHASES}
    phases["other"] = max(0.0, elapsed - sum(phases.values()))
    phases["total"] = elapsed
    directory = None if recorder is None else recorder.directory
    return {
        "mode": mode, "seconds": phases, "calls": dict(timings.calls), "action_log": action_log,
        "evidence_directory": None if directory is None else str(directory),
        "trace": None if directory is None else validate_trace(directory, arguments.actions, not arguments.no_screenshots),
    }


def print_summary(samples):
    """Show per-mode medians; individual measured samples remain in results.json."""
    measured = [sample for sample in samples if not sample["warmup"]]
    print(f"\n{'Median seconds':28s} {'Playwright baseline':>20s} {'Evidence':>11s} {'ASM':>11s}")
    medians = {}
    for phase in (*PHASES, "other", "total"):
        values = [median(s["seconds"][phase] for s in measured if s["mode"] == mode) for mode in MODES]
        medians[phase] = dict(zip(MODES, values))
        print(f"{phase:28s} {values[0]:20.3f} {values[1]:11.3f} {values[2]:11.3f}")
    baseline = medians["total"]["playwright_baseline"]
    print(f"\nEvidence/baseline: {medians['total']['evidence'] / baseline:.2f}x")
    print(f"ASM/baseline:     {medians['total']['asm'] / baseline:.2f}x")
    return medians


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--actions", type=int, default=20, help="Actions per sample")
    parser.add_argument("--repeats", type=int, default=3, help="Measured rounds; each includes all three modes")
    parser.add_argument("--warmups", type=int, default=1, help="Initial unmeasured rounds")
    parser.add_argument("--widgets", type=int, default=50, help="Additional non-actionable div/span widget pairs")
    parser.add_argument("--properties", type=int, default=4, help="Extra data attributes per widget pair's div")
    parser.add_argument("--states", type=int, default=5, help="Distinct page titles visited cyclically")
    parser.add_argument("--no-screenshots", action="store_true", help="Disable screenshots in the recording modes")
    parser.add_argument("--existing-trace", type=Path, action="append", default=[],
                        help="Historical evidence for ASM mode only; repeat to load several traces")
    parser.add_argument("--output", type=Path, default=Path("target/benchmarks"), help="Parent results directory")
    arguments = parser.parse_args()
    for name in ("actions", "repeats", "states"):
        if getattr(arguments, name) < 1:
            parser.error(f"--{name} must be positive")
    if arguments.warmups < 0 or not 0 <= arguments.widgets <= 2000 or not 0 <= arguments.properties <= 32:
        parser.error("warmups must be nonnegative; widgets must be 0..2000; properties must be 0..32")
    output = arguments.output / (datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f") + "-" + uuid4().hex[:6])
    output.mkdir(parents=True, exist_ok=False)
    samples = []
    with LocalFixture(output, arguments.widgets, arguments.properties, arguments.states) as fixture:
        with sync_playwright() as playwright:
            # Launch once outside samples. Each sample still gets isolated cookies and storage.
            browser = playwright.chromium.launch(headless=True)
            try:
                browser_version = browser.version
                for round_index in range(arguments.warmups + arguments.repeats):
                    reference_actions = None
                    # Rotate order so one mode is not always measured first.
                    order = MODES[round_index % 3:] + MODES[:round_index % 3]
                    for mode in order:
                        sample = run_sample(browser, fixture.url, mode, arguments, output / "traces")
                        if reference_actions is None:
                            reference_actions = sample["action_log"]
                        elif sample["action_log"] != reference_actions:
                            raise RuntimeError("Modes followed different action sequences; comparison rejected")
                        sample.update({"round": round_index + 1, "warmup": round_index < arguments.warmups})
                        samples.append(sample)
                        label = "Warm-up" if sample["warmup"] else "Measured"
                        print(f"{label} round {round_index + 1}, {mode}: {sample['seconds']['total']:.3f}s", flush=True)
                        # Save completed samples even if a later sample fails.
                        (output / "samples.json").write_text(json.dumps(samples, indent=4), encoding="utf-8")
            finally:
                browser.close()
    medians = print_summary(samples)
    result = {
        "settings": {key: str(value) if isinstance(value, Path)
                     else [str(path) for path in value] if key == "existing_trace" else value
                     for key, value in vars(arguments).items()},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "browser": browser_version, "playwright": version("playwright"),
                        "integration": version("testar-state-model-asm-playwright")},
        "samples": samples, "medians": medians,
    }
    (output / "results.json").write_text(json.dumps(result, indent=4), encoding="utf-8")
    print("Results and traces:", output.resolve())


if __name__ == "__main__":
    main()
