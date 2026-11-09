"""Level 1: scripted login, followed by default action derivation and ASM selection."""

import argparse
from pathlib import Path

from testar_evidence_playwright import sync_playwright
from testar_state_model_asm_playwright import default_configuration, explore


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
        # The integration derives actions; this script does not derive them.
        result = explore(page, default_configuration(arguments.actions),
                         state_without_actions=arguments.state_without_actions)
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
    arguments = parser.parse_args()
    if arguments.actions < 1:
        parser.error("--actions must be a positive integer")
    if arguments.sequences < 1:
        parser.error("--sequences must be a positive integer")
    # The evidence facade records the login and exploration in the same trace.
    # These optional arguments configure evidence recording, not ASM selection.
    # Calling sync_playwright() without them also enables automatic evidence recording.
    with sync_playwright(
        # Optional parent directory; the library default is target/traces.
        evidence_path=arguments.evidence_path,
        # Optional SUT label for trace names and metadata; the library default is "application".
        sut="parabank",
        # Optional test objective label for trace names and metadata; omitted by default.
        test_objective="Login followed by default exploration",
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
