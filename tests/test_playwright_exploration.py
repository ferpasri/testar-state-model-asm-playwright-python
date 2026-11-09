"""Small local pages explain action derivation, selection, execution, and saved evidence."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import Error as PlaywrightError, sync_playwright
from testar_evidence import EvidenceReader
from testar_evidence_playwright import CaptureOptions, sync_playwright as recorded_playwright
from testar_state_model_asm_playwright import (
    BrowserAction, ActionDerivationOptions, PlaywrightExploration, default_configuration, derive_actions, explore,
)


PAGES = {
    "/login": """<title>Login</title><input id="user"><button id="signin"
        onclick="location.href='/home'">Sign in</button>""",
    "/home": """<title>Home</title><button id="next"
        onclick="location.href='/form'">Open form</button>""",
    "/form": """<title>Form</title><input id="name" name="name"
        oninput="document.querySelector('#submit').disabled = !this.value">
        <button id="submit" disabled onclick="location.href='/done'">Submit</button>""",
    "/done": "<title>Done</title><p>Completed</p>",
    "/controls": """<title>Controls</title>
        <button id="visible">Visible</button><button hidden>Hidden</button>
        <button disabled>Disabled</button><button id="exclude">Excluded</button>
        <input id="configured"><input id="unsupplied"><input id="secret" type="password">
        <input id="readonly" readonly><a href="https://example.invalid/">External</a>
        <a href="/home" target="_blank">New tab</a>""",
}


class LocalApplication:
    """Serve deterministic pages so tests exercise real Playwright without an external SUT."""

    def __enter__(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content = PAGES.get(self.path, "<title>Missing</title>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml" if self.path.endswith(".wsdl")
                                 else "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class PlaywrightExplorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = LocalApplication()
        cls.site = cls.application.__enter__()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.application.__exit__()

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def options(self, **extra):
        return {
            "evidence_path": self.root,
            "capture_options": CaptureOptions(screenshots=False),
            "action_derivation_options": ActionDerivationOptions(input_values={"#name": "Alice"}),
            "choose_index": lambda size: 0,
            **extra,
        }

    def test_a_script_can_login_then_explore_without_deriving_actions_itself(self):
        # The customer's script prepares the application using native Playwright.
        self.page.goto(self.site.url + "/login")
        self.page.locator("#user").fill("demo")
        self.page.locator("#signin").click()
        # Action derivation offers Open form, then filling name, then the newly enabled Submit.
        # Unvisited chooses each action. The terminal page has no eligible actions.
        result = explore(self.page, default_configuration(10), **self.options(state_without_actions="stop"))
        self.assertEqual("no_available_choices", result.stopped["reason"])
        self.assertTrue(self.page.url.endswith("/done"))
        trace = EvidenceReader.read(result.evidence_directory)
        self.assertEqual(3, len(trace.action_executions))
        self.assertEqual(3, len(trace.recorded_transitions))
        # One initial state plus one resulting state per action; no extra capture for selection.
        self.assertEqual(4, len(trace.observations))
        self.assertTrue(all(r["status"] == "completed" for r in trace.action_executions.values()))
        self.assertTrue(all(o["available_action_scope"] == "eligible" for o in trace.observations.values()))

    def test_action_derivation_respects_visibility_filters_and_explicit_input_values(self):
        self.page.goto(self.site.url + "/controls")
        options = ActionDerivationOptions(input_values={"#configured": "text", "#secret": "password", "#readonly": "ignored"},
                                   excluded_selectors=("#exclude",))
        actions = derive_actions(self.page, options)
        self.assertEqual(["click", "fill", "fill"], [action.action_type for action in actions])
        self.assertEqual(["Click visible", "Fill configured", "Fill secret"], [action.name for action in actions])
        self.assertNotIn("password", repr(actions))

    def test_available_actions_are_retained_when_the_limit_stops_exploration(self):
        self.page.goto(self.site.url + "/home")
        result = explore(self.page, default_configuration(1), **self.options())
        self.assertEqual("action_limit_reached", result.stopped["reason"])
        trace = EvidenceReader.read(result.evidence_directory)
        self.assertEqual(1, len(trace.action_executions))
        final = list(trace.observations.values())[-1]
        self.assertEqual(1, len(final["available_actions"]))
        # Filling the form is known to be available but has not been executed.
        available = final["available_actions"][0]["action_description"]
        executed = {r["action_execution"]["action_description"] for r in trace.action_executions.values()}
        self.assertNotIn(available, executed)

    def test_a_disappeared_control_refreshes_without_recording_an_execution(self):
        self.page.goto(self.site.url + "/home")
        with PlaywrightExploration(self.page, default_configuration(1), **self.options()) as exploration:
            update = exploration.driver.observe()
            exploration.asm.update_evidence("initial", update.sources, update.selected_runs)
            exploration.asm.set_context(update.context)
            selection = exploration.asm.select()
            self.page.locator("#next").evaluate("element => element.remove()")
            self.assertIsNone(exploration.driver.prepare_execution(selection))
            refreshed = exploration.driver.observe()
            self.assertEqual([], refreshed.context["choices"])
            self.assertEqual({}, exploration.recorder.recorded_evidence.action_executions)

    def test_a_replacement_control_at_the_same_dom_path_requires_a_fresh_observation(self):
        self.page.goto(self.site.url + "/home")
        action = derive_actions(self.page)[0]
        self.page.locator("#next").evaluate("element => element.outerHTML = '<button>Different action</button>'")
        # The selector still finds a visible button, but it is not the derived control.
        self.assertFalse(action.applicable())

    def test_operation_failure_is_recorded_without_a_successful_transition(self):
        self.page.goto(self.site.url + "/home")
        with patch.object(BrowserAction, "execute", side_effect=PlaywrightError("Operation failed")):
            result = explore(self.page, default_configuration(1), **self.options())
        trace = EvidenceReader.read(result.evidence_directory)
        execution = next(iter(trace.action_executions.values()))
        self.assertEqual("failed", execution["status"])
        self.assertEqual([], trace.recorded_transitions)
        self.assertEqual(2, len(trace.observations))

    def test_historical_evidence_guides_navigation_to_a_known_unvisited_action(self):
        self.page.goto(self.site.url + "/home")
        first = explore(self.page, default_configuration(1), **self.options())
        # The first trace executed Open form and derived an unexecuted fill there.
        self.page.goto(self.site.url + "/home")
        with PlaywrightExploration(self.page, default_configuration(2),
                historical_traces=[first.evidence_directory], **self.options()) as exploration:
            update = exploration.driver.observe()
            history = EvidenceReader.read(first.evidence_directory)
            runs = [{"source": "historical:0", "run": record["test_run"]["id"]}
                    for record in history.test_runs.values()]
            exploration.asm.update_evidence("current", update.sources, runs + update.selected_runs)
            exploration.asm.set_context(update.context)
            selected = exploration.asm.select()
            self.assertEqual("navigate_to_unvisited_actions", selected["reason"])
            self.assertEqual(1, selected["navigation"]["distance"])

    def test_default_go_back_continues_until_the_normal_asm_action_limit(self):
        pages = {
            "/xml-origin": '<title>Service links</title><a href="/service.wsdl">Service</a>',
            "/service.wsdl": '<?xml version="1.0"?><definitions><service name="Demo"/></definitions>',
        }
        from examples.parabank_inputs_and_filters import wait_until_ready
        with patch.dict(PAGES, pages):
            self.page.goto(self.site.url + "/xml-origin")
            result = explore(self.page, default_configuration(10), **self.options(
                wait_until_ready=wait_until_ready))
        trace = EvidenceReader.read(result.evidence_directory)
        executions = list(trace.action_executions.values())
        types = [trace.action_descriptions[r["action_execution"]["action_description"]]["action_type"]
                 for r in executions]
        # Repeat XML visits and back navigation. No separate back counter stops them:
        # five clicks plus five back actions reach the ordinary ten-action ASM limit.
        self.assertEqual(["click", "go_back"] * 5, types)
        self.assertEqual("action_limit_reached", result.stopped["reason"])
        self.assertIsNone(executions[1]["action_execution"]["target_widget"])
        self.assertEqual(10, len(trace.recorded_transitions))
        self.assertEqual(11, len(trace.observations))

    def test_stop_policy_records_the_xml_result_without_a_back_action(self):
        pages = {
            "/xml-origin": '<title>Service links</title><a href="/service.wsdl">Service</a>',
            "/service.wsdl": '<?xml version="1.0"?><definitions/>',
        }
        with patch.dict(PAGES, pages):
            self.page.goto(self.site.url + "/xml-origin")
            result = explore(self.page, default_configuration(10), **self.options(state_without_actions="stop"))
        trace = EvidenceReader.read(result.evidence_directory)
        self.assertEqual("no_available_choices", result.stopped["reason"])
        self.assertEqual(1, len(trace.action_executions))
        self.assertEqual(2, len(trace.observations))
        self.assertEqual([], list(trace.observations.values())[-1]["available_actions"])

    def test_an_empty_page_without_back_history_stops_without_executing(self):
        self.page.goto(self.site.url + "/done")
        result = explore(self.page, default_configuration(10), **self.options(state_without_actions="go_back"))
        self.assertEqual("no_available_choices", result.stopped["reason"])
        self.assertEqual({}, EvidenceReader.read(result.evidence_directory).action_executions)

    def test_custom_action_derivation_and_action_filter_are_independent_of_the_asm(self):
        self.page.goto(self.site.url + "/home")
        def derive_actions(page, options):
            return [BrowserAction("click", "Custom action", page.locator("#next"))]
        result = explore(self.page, default_configuration(1),
                         **self.options(derive_actions=derive_actions, allow_action=lambda action: False))
        self.assertEqual("no_available_choices", result.stopped["reason"])
        self.assertEqual(0, len(EvidenceReader.read(result.evidence_directory).action_executions))


    def test_password_values_are_redacted_in_saved_execution_parameters(self):
        self.page.goto(self.site.url + "/controls")
        value = "unique-password-783"
        result = explore(self.page, default_configuration(1), **self.options(
            action_derivation_options=ActionDerivationOptions(input_values={"#secret": value}),
            allow_action=lambda action: action.action_type == "fill"))
        trace = EvidenceReader.read(result.evidence_directory)
        record = next(iter(trace.action_executions.values()))
        self.assertNotIn("value", record["action_execution"]["parameters"])
        self.assertIn("value", record["action_execution"]["parameters"]["playwright.redacted_parameters"])
        # Password values must not enter descriptions, captured widgets, or event JSON.
        content = "\\n".join(path.read_text(encoding="utf-8") for path in result.evidence_directory.glob("*.jsonl"))
        self.assertNotIn(value, content)

    def test_screenshot_artifacts_survive_a_complete_exploration_trace(self):
        self.page.goto(self.site.url + "/home")
        result = explore(self.page, default_configuration(1), **self.options(
            capture_options=CaptureOptions(screenshots=True)))
        trace = EvidenceReader.read(result.evidence_directory)
        self.assertEqual(2, len(trace.observations))
        self.assertTrue(all(any(a["media_type"] == "image/png" for a in o["artifacts"])
                            for o in trace.observations.values()))


class FacadeExplorationTests(unittest.TestCase):
    def test_an_existing_evidence_facade_does_not_record_the_asm_action_twice(self):
        with TemporaryDirectory() as directory, LocalApplication() as site:
            with recorded_playwright(evidence_path=directory,
                                     capture_options=CaptureOptions(screenshots=False)) as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(site.url + "/home")
                    result = explore(page, default_configuration(1), choose_index=lambda size: 0)
                finally:
                    browser.close()
            trace = EvidenceReader.read(result.evidence_directory)
            # One scripted navigation and one ASM click, each recorded exactly once.
            self.assertEqual(2, len(trace.action_executions))
            self.assertEqual(2, len(trace.recorded_transitions))
