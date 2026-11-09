"""Run the demo scripts against local ParaBank-shaped pages, not the public service."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from testar_abstraction import parse_abstraction_rules
from testar_evidence import EvidenceReader

from examples.parabank_custom_asm import exploration_configuration
from tests.test_playwright_exploration import LocalApplication, PAGES


ROOT = Path(__file__).resolve().parents[1]
LOGIN = """<title>Customer Login</title>
    <input name="username"><input name="password" type="password">
    <button onclick="if(document.querySelector('[name=username]').value === 'john'
        && document.querySelector('[name=password]').value === 'demo') location.href='/overview'">Log In</button>
    <script>
        // A reused context would keep this marker and make the next login fail.
        if (localStorage.getItem('sequence_started')) {
            document.querySelector('[name=username]').remove();
        }
        localStorage.setItem('sequence_started', 'true');
    </script>"""
OVERVIEW = """<title>Accounts Overview</title>
    <div id="leftPanel"><h2>Account Services</h2>
    <a href="/requestloan.htm">Request Loan</a><a href="/logout.htm">Log Out</a></div>
    <div id="rightPanel"><h1>Accounts Overview</h1></div>"""
LOAN = """<title>Loan Request</title>
    <div id="leftPanel"><h2>Account Services</h2><a href="/logout.htm">Log Out</a></div>
    <div id="rightPanel"><h1>Apply for a Loan</h1>
    <input id="amount"><input id="downPayment"><button>Apply Now</button></div>"""


class ParaBankExampleTests(unittest.TestCase):
    def test_each_standalone_demo_runs_two_sequences_with_fresh_browser_state(self):
        pages = {"/": LOGIN, "/overview": OVERVIEW, "/requestloan.htm": LOAN, "/logout.htm": LOGIN}
        with patch.dict(PAGES, pages), LocalApplication() as site, TemporaryDirectory() as directory:
            historical = None
            for module in ("parabank_basic", "parabank_inputs_and_filters", "parabank_custom_asm"):
                with self.subTest(example=module):
                    output = Path(directory) / module
                    # Copy only this script outside the repository: no other example
                    # files should be needed to log in and start exploration.
                    script = Path(directory) / (module + ".py")
                    shutil.copy2(ROOT / "examples" / (module + ".py"), script)
                    command = [sys.executable, "-X", "utf8", str(script),
                               "--url", site.url + "/", "--actions", "1", "--sequences", "2", "--headless",
                               "--evidence-path", str(output)]
                    if module == "parabank_custom_asm":
                        command.extend(["--existing-trace", str(historical)])
                    completed = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                                               encoding="utf-8", timeout=60)
                    self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                    self.assertIn("Stop reason: action_limit_reached", completed.stdout)
                    manifests = list(output.rglob("manifest.json"))
                    self.assertEqual(2, len(manifests))
                    self.assertEqual(2, completed.stdout.count("Stop reason: action_limit_reached"))
                    identifiers = set()
                    for manifest in manifests:
                        trace = EvidenceReader.read(manifest.parent)
                        identifiers.add(trace.manifest["evidence_id"])
                        # Each independent sequence records four scripted actions and
                        # one ASM action; the first sequence does not consume its limit.
                        self.assertEqual(5, len(trace.action_executions))
                        self.assertTrue(all(record["status"] == "completed"
                                            for record in trace.action_executions.values()))
                        self.assertTrue(all(record["status"] == "finished"
                                            for record in trace.test_runs.values()))
                    self.assertEqual(2, len(identifiers))
                    if module == "parabank_inputs_and_filters":
                        historical = manifests[0].parent

    def test_stop_on_an_empty_xml_page_finishes_the_trace_and_runs_the_next_sequence(self):
        pages = {
            "/": LOGIN,
            "/overview": '<title>Accounts Overview</title><h2>Account Services</h2>'
                         '<div id="rightPanel"><a href="/service.wsdl">Service</a></div>',
            "/service.wsdl": '<?xml version="1.0"?><definitions/>',
        }
        with patch.dict(PAGES, pages), LocalApplication() as site, TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "examples/parabank_inputs_and_filters.py"),
                 "--url", site.url + "/", "--actions", "20", "--sequences", "2", "--headless",
                 "--state-without-actions", "stop", "--evidence-path", directory],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual(2, completed.stdout.count("Stop reason: no_available_choices"))
            manifests = list(Path(directory).rglob("manifest.json"))
            self.assertEqual(2, len(manifests))
            for manifest in manifests:
                trace = EvidenceReader.read(manifest.parent)
                self.assertEqual(5, len(trace.action_executions))
                self.assertTrue(all(r["status"] == "finished" for r in trace.test_runs.values()))

    def test_custom_asm_example_configuration_uses_the_supported_abstraction_language(self):
        configuration = exploration_configuration(30)
        parsed = parse_abstraction_rules(json.dumps(configuration["abstraction"]))
        self.assertEqual("same", parsed["capture"])
        self.assertEqual(["unvisited", "random"], [asm["name"] for asm in configuration["asms"]])
        self.assertEqual([5, 3], [asm["action_limit"] for asm in configuration["asms"]])
        self.assertEqual(30, configuration["total_action_limit"])
