"""A script can prepare the application, then hand its page to ASM exploration."""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from testar_evidence_playwright import PlaywrightEvidence, evidence_for
from testar_state_model_asm import AsmRun, read_source

from .driver import PlaywrightExplorationDriver


def default_configuration(action_limit=20):
    """Use page address/title and target identity, trying Unvisited then Random."""
    if type(action_limit) is not int or action_limit <= 0:
        raise ValueError("action_limit must be a positive integer")
    return {
        "abstraction": {
            "version": 1, "name": "Page address, title, and target identity",
            "state": [
                {"name": "address", "keys": ["ui.url"], "required": True},
                {"name": "title", "keys": ["ui.title"], "required": True},
            ],
            "capture": "same",
            "actions": {"target": [
                {"name": "target", "keys": [
                    "playwright.attribute.id", "playwright.attribute.name", "playwright.dom.path"
                ], "required": True},
            ]},
        },
        "asms": [
            {"name": "unvisited", "action_limit": action_limit, "unmatched_choices": "exclude"},
            {"name": "random", "action_limit": action_limit},
        ],
        "total_action_limit": action_limit,
    }


@dataclass(frozen=True)
class ExplorationResult:
    """Why exploration stopped, its abstract model, and where its evidence was saved."""

    stopped: dict
    model: dict
    evidence_directory: Path


class PlaywrightExploration:
    """Keep the ASM, evidence recorder, and Playwright driver together for one page."""

    def __init__(self, page, configuration=None, *, recorder=None, evidence_path="target/traces",
                 sut="application", test_objective=None, capture_options=None, historical_traces=(),
                 action_derivation_options=None, derive_actions=None, allow_action=None, wait_until_ready=None,
                 action_timeout=5000, choose_index=None, state_without_actions="go_back"):
        """Load optional historical traces and connect the page to an independent ASM run."""
        configuration = default_configuration() if configuration is None else deepcopy(configuration)
        sources = []
        selected_runs = []
        for index, directory in enumerate(historical_traces):
            source = read_source(directory, source_id=f"historical:{index}")
            sources.append(source)
            selected_runs.extend({"source": source["id"], "run": run["id"]} for run in source["evidence"]["runs"])
        self.asm = AsmRun(configuration, sources, selected_runs, choose_index=choose_index)
        self._owns_recorder = False
        if recorder is None:
            try:
                recorder = evidence_for(page)
            except ValueError:
                recorder = PlaywrightEvidence.start_trace(
                    evidence_path, page, sut=sut, test_objective=test_objective, options=capture_options,
                    origin="testar-state-model-asm-playwright-python")
                self._owns_recorder = True
        self.recorder = recorder
        try:
            self.driver = PlaywrightExplorationDriver(
                page, recorder, action_derivation_options=action_derivation_options, derive_actions=derive_actions,
                allow_action=allow_action, wait_until_ready=wait_until_ready, action_timeout=action_timeout,
                state_without_actions=state_without_actions)
        except BaseException:
            self.close()
            raise

    def run(self, *, max_cycles=1000):
        """Let the ASM control exploration and retain its model for inspection."""
        self.driver.refresh_on_next_observation()
        stopped = self.asm.explore(self.driver, max_cycles=max_cycles)
        return ExplorationResult(stopped, self.asm.model, self.recorder.directory)

    def close(self):
        """Finish an owned evidence trace; leave a caller's recorder and browser open."""
        if self._owns_recorder:
            self.recorder.close()

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        try:
            self.close()
        except Exception as cleanup:
            if exception is None:
                raise
            exception.add_note("Evidence cleanup also failed: " + str(cleanup))


def explore(page, configuration=None, **options):
    """Start exploration on an existing page and return its model and stop reason."""
    max_cycles = options.pop("max_cycles", 1000)
    with PlaywrightExploration(page, configuration, **options) as exploration:
        return exploration.run(max_cycles=max_cycles)
