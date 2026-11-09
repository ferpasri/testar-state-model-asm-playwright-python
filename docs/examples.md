# ParaBank exploration examples

Each example logs in to ParaBank with the public demo credentials john/demo, then starts exploration on the authenticated page. Each script contains its own browser setup, login calls, configuration, exploration call, and cleanup. Its run_sequence() function performs one sequence, while main() reads arguments and repeats it as requested. It imports only standard Python modules and the installed libraries, so it can be copied and run independently.

| Example | What the script supplies | What the integration supplies |
| --- | --- | --- |
| [Basic](../examples/parabank_basic.py) | Login and an action count limit. | Default action derivation, abstraction, Unvisited selection with Random fallback, execution, and evidence. |
| [Inputs and filters](../examples/parabank_inputs_and_filters.py) | Loan input values, excluded controls, and a readiness callback. | Action derivation within those settings and ASM-controlled action selection. |
| [Custom ASM](../examples/parabank_custom_asm.py) | Custom abstraction, alternating ASMs, and optional historical trace directories. | Model construction from those traces and live updates during exploration. |

Run the commands below from the repository root, using an environment with the project and its dependencies installed. All scripts use the evidence facade, so login and exploration are recorded together in a new trace beneath target/traces.

## 1. Login and default exploration

~~~powershell
python examples/parabank_basic.py --actions 10 --headless
~~~

The script shows the login steps directly, followed by explore(page, default_configuration(...)). The integration derives available clicks and selects and executes them. Default action derivation offers fills only when values have been supplied, so this example explores clicks without generating form input. Logout remains an eligible link.

## 2. Input values, exclusions, and readiness

~~~powershell
python examples/parabank_inputs_and_filters.py --actions 20 --headless
~~~

ActionDerivationOptions supplies 999999 for #amount and 1 for #downPayment when those loan fields are present. It excludes links containing logout.htm or admin.htm. The readiness callback waits for DOMContentLoaded without requiring a particular application panel, so it also accepts XML/WSDL and unexpected pages.

These settings make fill actions available; the ASM chooses when to execute them. They do not enforce the sequence fill amount -> fill down payment -> Apply Now. A workflow with a required order belongs in scripted preparation or an explicit action derivation/filtering policy.

DOMContentLoaded does not guarantee that asynchronous application content has finished loading. A custom readiness callback can wait for such content, but must account for other states exploration may reach. A wrongly customized callback can time out before action derivation; this error propagates to the caller.

## 3. Custom abstraction and historical traces

Start without historical evidence:

~~~powershell
python examples/parabank_custom_asm.py --actions 30 --headless
~~~

Then copy the individual trace directory printed by a previous run:

~~~powershell
python examples/parabank_custom_asm.py --actions 30 --headless --existing-trace "target/traces/PASTE_PREVIOUS_TRACE_DIRECTORY"
~~~

Repeat --existing-trace for several individual trace directories. Each directory contains its own manifest and event JSONL. Historical evidence provides recorded states and actions; the script still performs a fresh login.

The example's configuration:

- Removes the explicitly named session parameters and fragments from page addresses during matching. Original addresses remain in the evidence.
- Includes captured widget text and display/visibility styles in state comparison. Changing those values can produce a different abstract state.
- Uses the default action-target comparison by captured ID, name, or DOM path.
- Allocates five actions to Unvisited and three to Random, repeating until the overall action count limit. An ASM can also switch early when it cannot select.

The current and historical records are compared using these same rules. The rules are example choices for this demo: changing text or DOM structure may require a different abstraction for another exploration objective.

## Repeat sequences

~~~powershell
python examples/parabank_inputs_and_filters.py --sequences 3 --actions 10 --headless
~~~

main() launches the browser once and calls run_sequence() three times. Each call creates a fresh browser context, performs login, starts an independent ASM, and closes the context to finish its evidence trace. Each sequence therefore has its own trace directory and action count limit.

Fresh contexts clear browser cookies and storage. They do not undo server-side changes such as submitted loan requests. A complete SUT reset requires an application-specific reset operation.

Earlier sequences are not automatically added to the next ASM. In the custom ASM example, each sequence loads the same explicitly supplied --existing-trace traces. Each sequence keeps its own new evidence.

## XML/WSDL pages and other empty pages

The library and examples default to --state-without-actions go_back. When a page has no eligible widget actions, the integration offers a recorded browser-back action if history is available. The configured ASM selects it. Back actions count toward the per-sequence action limit.

Choose --state-without-actions stop to finish the current sequence immediately when no eligible actions remain, then run the next sequence:

~~~powershell
python examples/parabank_inputs_and_filters.py --sequences 3 --actions 20 --state-without-actions stop
~~~

If browser back is unavailable, exploration stops and the sequence runner continues. The examples wait for document loading without requiring a ParaBank-specific panel. Errors from a custom readiness callback still propagate.

## Options and results

Every command-line argument is optional. Running a script without arguments opens ParaBank, performs login, then runs one sequence with a limit of ten ASM actions. Use --help to read the options and their defaults.

| Argument | Purpose | Default |
| --- | --- | --- |
| --url | ParaBank address opened before login. | https://para.testar.org/ |
| --actions | Positive ASM action count limit per sequence; scripted login actions are separate. | 10 |
| --sequences | Number of independent sequences to execute. | 1 |
| --state-without-actions | Offer browser back on an empty page (go_back), or stop the sequence (stop). | go_back |
| --headless | Hide the browser window. | Window displayed |
| --evidence-path | Parent folder for a new timestamped trace directory. | target/traces |
| --existing-trace | Individual historical trace directory; repeat for several traces. Only the custom ASM example accepts this option. | No historical traces |

The scripts also show three optional evidence-facade parameters beside their invocation: evidence_path selects the parent output folder, sut labels the SUT, and test_objective labels the test objective. Calling sync_playwright() without them uses target/traces, the SUT label application, and no supplied test objective. These parameters describe evidence recording; the configuration passed to explore() controls ASM behavior.

~~~powershell
python examples/parabank_inputs_and_filters.py --actions 15 --evidence-path target/parabank-traces
~~~

Each script prints the stop reason and the evidence directory. Load that individual directory in the dashboard. Exploration returns an abstract model in memory; the evidence directory contains concrete recorded facts.

The john/demo values are public demo credentials. For another application, obtain credentials through the application's usual secret configuration.

[Implementation specifications](SPEC.md) describe the supported action derivation and execution behavior.
