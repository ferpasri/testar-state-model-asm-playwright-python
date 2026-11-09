# TESTAR Playwright ASM Python

Add model-based exploration to a synchronous Playwright script. The integration derives actions on the current page, lets the ASM select one, executes it through Playwright, and records concrete evidence.

~~~python
from playwright.sync_api import sync_playwright
from testar_state_model_asm_playwright import ActionDerivationOptions, default_configuration, explore

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page()
    page.goto("https://your-application.example/")

    # Keep existing scripted preparation, such as login, before this call.
    result = explore(
        page,
        default_configuration(action_limit=20),
        action_derivation_options=ActionDerivationOptions(
            input_values={"input[name='search']": "example"},
            excluded_selectors=("a[href*='logout']",),
        ),
    )
    print(result.stopped["reason"])
    print(result.evidence_directory)
    browser.close()
~~~

The default configuration uses Unvisited ASM, with Random as a fallback, and stops at the overall action limit or when no eligible action remains. It groups states by page address and title. Supply your own configuration to select different abstraction rules and ASMs.

Default action derivation offers visible enabled buttons and same-origin links, and fills for fields with explicitly configured values. For states without eligible widget actions, state_without_actions="go_back" is the default; use "stop" to end exploration instead. [Specifications](docs/SPEC.md) describe customization, evidence coordination, and supported page scope.

Native Playwright pages create a new timestamped evidence trace when exploration starts. Pages created through the evidence facade reuse their recorder, so scripted preparation and exploration can share a trace. You can also supply an explicit recorder.

## Install and run

Install the declared dependencies from your package source or their built wheels, then install this repository:

~~~powershell
python -m pip install .
python -m playwright install chromium
python -m unittest discover -s tests -t . -v
python -m pip wheel --no-deps . -w dist
~~~

The project uses normal package dependencies declared in [pyproject.toml](pyproject.toml). The [examples guide](docs/examples.md) walks through ParaBank login followed by basic exploration, inputs and filters, and custom ASM configuration with optional existing traces.

## Components

| Component | Purpose |
| --- | --- |
| BrowserAction | An available click/fill with a widget locator, or a browser-history back action without a widget target. |
| ActionDerivationOptions | Input values, excluded controls, link scope, and the action derivation limit. |
| PlaywrightExplorationDriver | Observe, derive actions, check applicability, execute, and report evidence to the ASM. |
| PlaywrightExploration | Keep the ASM and driver together; expose the resulting model and manage an owned recorder. |
| explore | Run exploration on an existing page and return its stop reason, model, and evidence directory. |

The [browser tests](tests/test_playwright_exploration.py) use local pages to demonstrate the complete integration. Remaining work is in [TODO](TODO.md).

## Benchmark

Compare an X-action Playwright baseline script (no ASM or evidence), the same actions with evidence recording, and ASM exploration with evidence:

~~~powershell
.\.venv\Scripts\python.exe benchmarks/benchmark_exploration.py --actions 20 --repeats 3 --warmups 1
.\.venv\Scripts\python.exe benchmarks/benchmark_exploration.py --actions 20 --repeats 3 --warmups 1 --no-screenshots
~~~

The [benchmark guide](benchmarks/README.md) explains dataset size, historical evidence, timing categories, and saved results.
