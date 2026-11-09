"""Local fixture and benchmark-only timing; production recording remains unchanged."""

from collections import defaultdict
from contextlib import contextmanager, ExitStack
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import perf_counter
from unittest.mock import patch

from testar_evidence_playwright import evidence as evidence_module
from testar_state_model_asm_playwright import BrowserAction


PHASES = (
    "startup", "model_setup", "readiness", "discovery", "applicability",
    "browser_actions", "dom_capture", "screenshots", "recording",
    "model_update", "selection", "coordination", "cleanup",
)


class Timings:
    """Count each elapsed interval once, subtracting nested work from its parent."""

    def __init__(self, clock=perf_counter):
        self.clock = clock
        self.seconds = defaultdict(float)
        self.calls = defaultdict(int)
        self._stack = []

    @contextmanager
    def measure(self, phase):
        frame = {"started": self.clock(), "children": 0.0}
        self._stack.append(frame)
        try:
            yield
        finally:
            elapsed = self.clock() - frame["started"]
            self._stack.pop()
            self.seconds[phase] += elapsed - frame["children"]
            self.calls[phase] += 1
            if self._stack:
                self._stack[-1]["children"] += elapsed

    def wrap(self, phase, operation):
        """Time an existing operation without changing its inputs, result, or exceptions."""
        @wraps(operation)
        def measured(*arguments, **options):
            with self.measure(phase):
                return operation(*arguments, **options)
        return measured


class LocalFixture:
    """Serve the saved generated HTML to every mode using the same local address."""

    def __init__(self, directory, widgets, properties, states):
        template = Path(__file__).with_name("fixture.html").read_text(encoding="utf-8")
        controls = []
        for index in range(widgets):
            attributes = " ".join(f'data-property-{item}="widget-{index}-value-{item}"'
                                  for item in range(properties))
            controls.append(f'<div class="widget" {attributes}><span>Widget {index}</span></div>')
        self.document = template.replace("{{widgets}}", "\n".join(controls)).replace("{{states}}", str(states))
        (directory / "fixture.html").write_text(self.document, encoding="utf-8")

    def __enter__(self):
        content = self.document.encode("utf-8")
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@contextmanager
def recording_timings(timings, page, recorder=None, asm=None, driver=None):
    """Instrument installed objects only for this sample, restoring them afterwards."""
    actions = []
    with ExitStack() as scope:
        execute = BrowserAction.execute
        def execute_action(action, timeout):
            actions.append({"type": action.action_type, "locator": str(action.locator)})
            return timings.wrap("browser_actions", execute)(action, timeout)
        scope.enter_context(patch.object(BrowserAction, "execute", execute_action))
        scope.enter_context(patch.object(BrowserAction, "applicable",
                                        timings.wrap("applicability", BrowserAction.applicable)))
        scope.enter_context(patch.object(page, "screenshot", timings.wrap("screenshots", page.screenshot)))
        scope.enter_context(patch.object(evidence_module, "capture_page",
                                        timings.wrap("dom_capture", evidence_module.capture_page)))
        if recorder is not None:
            for name in ("capture", "record_available_actions", "commit_capture",
                         "select_recorded_action", "execute_selected"):
                scope.enter_context(patch.object(recorder, name, timings.wrap("recording", getattr(recorder, name))))
            original = type(recorder).recorded_evidence.fget
            scope.enter_context(patch.object(type(recorder), "recorded_evidence",
                                            property(timings.wrap("recording", original))))
        if driver is not None:
            for name in ("observe", "prepare_execution", "execute"):
                scope.enter_context(patch.object(driver, name, timings.wrap("coordination", getattr(driver, name))))
        if asm is not None:
            for name, phase in (("update_evidence", "model_update"), ("report_execution", "model_update"),
                                ("set_context", "coordination"), ("select", "selection"),
                                ("begin_execution", "coordination")):
                scope.enter_context(patch.object(asm, name, timings.wrap(phase, getattr(asm, name))))
        yield actions
