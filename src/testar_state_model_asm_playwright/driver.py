"""Connect ASM observation and execution requests to Playwright and evidence recording."""

from uuid import uuid4
import math

from playwright.sync_api import Error as PlaywrightError
from testar_evidence_playwright import AvailableAction
from testar_state_model_asm import ObservationUpdate, ExecutionUpdate, evidence_source

from .action_derivation import BrowserAction, ActionDerivationOptions, derive_actions as default_derive_actions


class PlaywrightExplorationDriver:
    """Derive actions, record their state, and execute the ASM's selected current choice."""

    def __init__(self, page, recorder, *, action_derivation_options=None, derive_actions=None,
                 allow_action=None, wait_until_ready=None, action_timeout=5000,
                 state_without_actions="go_back"):
        """Use the supplied page and recorder, with optional action derivation and readiness behavior."""
        if (isinstance(action_timeout, bool) or not isinstance(action_timeout, (int, float))
                or not math.isfinite(action_timeout) or action_timeout <= 0):
            raise ValueError("action_timeout must be a positive number of milliseconds")
        if state_without_actions not in {"stop", "go_back"}:
            raise ValueError("state_without_actions must be go_back or stop")
        self.state_without_actions = state_without_actions
        self.page = page
        self.recorder = recorder
        self.options = action_derivation_options or ActionDerivationOptions()
        self.derive_actions = derive_actions or default_derive_actions
        self.allow_action = allow_action or (lambda action: True)
        self.wait_until_ready = wait_until_ready or (lambda page: page.wait_for_load_state("domcontentloaded"))
        self.action_timeout = action_timeout
        self.source_id = recorder.run_id
        self._choices = {}
        self._observation = None
        self._next_observation = None

    def refresh_on_next_observation(self):
        """Discard a cached result context after the caller has run additional script steps."""
        self._next_observation = None

    def _snapshot(self):
        """Expose committed evidence to the ASM without rereading the trace from disk."""
        source = evidence_source(self.recorder.recorded_evidence, self.source_id)
        return [source], [{"source": self.source_id, "run": self.recorder.run_id}]

    def observe(self):
        """Save one current state with its eligible actions before the ASM makes a selection."""
        if self._next_observation is not None:
            observation = self._next_observation
            self._next_observation = None
            return observation
        return self._observe_current()

    def _observe_current(self):
        """Capture and derive once; the result also supplies the next selection context."""
        self.wait_until_ready(self.page)
        observation = self.recorder.capture()
        derived_actions = self.derive_actions(self.page, self.options)
        actions = [action for action in derived_actions if self.allow_action(action)]
        if not actions and self.state_without_actions == "go_back":
            # Browser navigation is an available action without a widget target.
            back = BrowserAction("go_back", "Go back in browser history", None, page=self.page)
            if back.applicable() and self.allow_action(back):
                actions.append(back)
        descriptions = [AvailableAction(action.action_type, action.name, action.locator) for action in actions]
        self.recorder.record_available_actions(descriptions, scope="eligible", observation=observation)
        self.recorder.commit_capture()
        sources, selected_runs = self._snapshot()
        recorded = next(item for item in sources[0]["evidence"]["observations"] if item["id"] == observation)
        bindings = {binding["action_description"]: binding for binding in recorded["available_actions"]}
        choices = []
        self._choices = {}
        for action, description in zip(actions, descriptions):
            identifier = description.description().id
            binding = bindings[identifier]
            # Uncaptured targets remain recorded evidence but cannot guide a model-based click.
            if ((binding["target_widget"] is None and action.action_type != "go_back")
                    or identifier in self._choices):
                continue
            self._choices[identifier] = (action, description)
            choices.append({"choice_id": identifier, **binding})
        self._observation = observation
        return ObservationUpdate({
            "context_id": uuid4().hex,
            "observation": {"source": self.source_id, "run": self.recorder.run_id, "observation": observation},
            "choices": choices,
        }, sources, selected_runs)

    def prepare_execution(self, selection):
        """Recheck the selected control; refresh the observation if it is no longer usable."""
        action, description = self._choices[selection["choice_id"]]
        try:
            if not action.applicable():
                return None
        except PlaywrightError:
            if self.page.is_closed():
                raise
            return None
        parameters = {"value": action.value} if action.action_type == "fill" else {}
        execution = self.recorder.select_recorded_action(description, self._observation, parameters)
        return {"source": self.source_id, "run": self.recorder.run_id, "execution": execution}

    def execute(self, selection, execution):
        """Record the operation outcome and resulting state before updating the ASM."""
        action, _ = self._choices[selection["choice_id"]]
        try:
            self.recorder.execute_selected(lambda: action.execute(self.action_timeout))
        except PlaywrightError:
            # The evidence adapter already recorded the failed operation. Capture the
            # current GUI so exploration can reassess it rather than reuse the old state.
            if self.page.is_closed():
                return ExecutionUpdate(*self._snapshot())
        # Derive result-state actions now so the ASM can immediately use them.
        # Reuse this same saved observation on the next cycle rather than recapturing it.
        self._next_observation = self._observe_current()
        return ExecutionUpdate(self._next_observation.sources, self._next_observation.selected_runs)
