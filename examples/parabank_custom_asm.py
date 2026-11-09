"""Level 3: custom abstraction and ASM switching, optionally guided by previous traces."""

import argparse
from pathlib import Path

from testar_evidence_playwright import sync_playwright
from testar_state_model_asm_playwright import ActionDerivationOptions, default_configuration, explore


def exploration_configuration(action_limit):
    """Choose how observations/actions match and how Unvisited and Random alternate."""
    configuration = default_configuration(action_limit)
    abstraction = configuration["abstraction"]
    abstraction["name"] = "ParaBank address, content, and target without session data"
    # Remove session data only for comparison; the trace retains the original URL.
    abstraction["state"][0]["transforms"] = [{
        "op": "url",
        "remove_path_parameters": ["JSESSIONID_8111", "jsessionid"],
        "remove_query": ["session"],
        "remove_fragment": True,
    }]
    # This example treats captured text and visibility styles as part of state identity.
    # Thus changing form/result content can produce a different abstract state.
    abstraction["widgets"] = {
        "fields": [
            {"name": "tag", "keys": ["playwright.dom.tagName"]},
            {"name": "text", "keys": ["ui.text"]},
            {"name": "display", "keys": ["playwright.style.display"]},
            {"name": "visibility", "keys": ["playwright.style.visibility"]},
        ],
        "hierarchy": "flat", "order": "sort", "descendants": "exclude",
    }
    # Five invoked actions with Unvisited, then three with Random, repeating until
    # the overall limit. An ASM can also switch early when it cannot select.
    configuration["asms"] = [
        {"name": "unvisited", "action_limit": 5, "unmatched_choices": "exclude"},
        {"name": "random", "action_limit": 3},
    ]
    return configuration


def wait_until_ready(page):
    """Wait for document loading without assuming which page exploration reached."""
    # Exploration can reach HTML, XML, or an unexpected page without ParaBank's layout.
    page.wait_for_load_state("domcontentloaded")


def run_sequence(browser, arguments):
    """Run scripted login and an independent ASM using a fresh browser context."""
    # A new context clears browser cookies and storage. It does not reset server-side SUT data.
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(15_000)
        # Scripted preparation: log in before handing control to the ASM.
        page.goto(arguments.url)
        page.locator("input[name='username']").fill("john")
        page.locator("input[name='password']").fill("demo")
        page.get_by_role("button", name="Log In", exact=True).click()
        # Wait until login finishes; this wait does not record an oracle result.
        page.get_by_text("Account Services", exact=True).wait_for(state="visible")
        # Historical traces supply model data, not a saved browser session.
        result = explore(
            page,
            exploration_configuration(arguments.actions),
            historical_traces=arguments.existing_trace,
            # Offer these fills only where the fields exist; keep Logout excluded.
            action_derivation_options=ActionDerivationOptions(
                input_values={"#amount": "999999", "#downPayment": "1"},
                excluded_selectors=("a[href*='logout.htm']", "a[href*='admin.htm']"),
            ),
            wait_until_ready=wait_until_ready,
            # Offer a recorded back action on empty pages, or end this sequence.
            state_without_actions=arguments.state_without_actions,
        )
        return result
    finally:
        # Closing the context finishes this page's evidence trace, including on failure.
        context.close()


def main():
    # All command-line arguments are optional; running this file without them uses these defaults.
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--url", default="https://para.testar.org/",
                        help="Optional ParaBank address opened before the scripted login")
    parser.add_argument("--actions", type=int, default=10,
                        help="Optional positive ASM action limit per sequence; scripted login actions are not counted")
    parser.add_argument("--sequences", type=int, default=1,
                        help="Optional positive sequence count; each starts with fresh browser state and ASM")
    parser.add_argument("--state-without-actions", choices=("go_back", "stop"), default="go_back",
                        help="Optional empty-page policy: try recorded browser back, or stop this sequence")
    parser.add_argument("--headless", action="store_true",
                        help="Optional flag to hide the browser; otherwise its window is displayed")
    parser.add_argument("--evidence-path", type=Path, default=Path("target/traces"),
                        help="Optional parent folder for new timestamped evidence trace directories")
    parser.add_argument("--existing-trace", type=Path, action="append", default=[],
                        help="Optional individual trace directory; repeat for several traces, omit to start without history")
    arguments = parser.parse_args()
    if arguments.actions < 1:
        parser.error("--actions must be a positive integer")
    if arguments.sequences < 1:
        parser.error("--sequences must be a positive integer")
    # These optional arguments configure evidence recording, not ASM selection.
    # Calling sync_playwright() without them also enables automatic evidence recording.
    with sync_playwright(
        # Optional parent directory; the library default is target/traces.
        evidence_path=arguments.evidence_path,
        # Optional SUT label for trace names and metadata; the library default is "application".
        sut="parabank",
        # Optional test objective label for trace names and metadata; omitted by default.
        test_objective="Explore using custom abstraction and historical evidence",
    ) as playwright:
        browser = playwright.chromium.launch(headless=arguments.headless)
        try:
            for sequence_index in range(1, arguments.sequences + 1):
                print(f"Sequence {sequence_index} of {arguments.sequences}")
                result = run_sequence(browser, arguments)
                print("Stop reason:", result.stopped["reason"])
                print("Evidence directory:", result.evidence_directory)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
