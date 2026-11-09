# Local exploration benchmark

This benchmark compares the cost of the same browser interactions in three modes:

| Mode | How the next action is chosen | Evidence recording | ASM/model |
| --- | --- | --- | --- |
| playwright_baseline | An X-action benchmark script takes the fixture's only eligible action and executes it through Playwright. | No | No |
| evidence | The same benchmark choice is executed through the recording driver. | Yes | No |
| asm | The real ASM selects the action and controls exploration through the recording driver. | Yes | Yes |

Playwright supplies browser operations such as click and fill; it does not supply an ASM. In playwright_baseline, the control logic belongs to this benchmark script. With --actions 20 it discovers and executes exactly 20 actions. Discovery uses this integration's shared helper so the modes perform comparable discovery work.

The fixture alternates a button click and a text fill. Exactly one action is eligible at each step, so all modes execute the same action sequence. The runner rejects comparisons with different action logs or incorrect trace counts. This fixture measures execution overhead; it does not measure which ASM finds more states or how effectively it navigates branches.

## Run

From the repository root using the environment containing the installed libraries:

~~~powershell
.\.venv\Scripts\python.exe benchmarks/benchmark_exploration.py --actions 20 --repeats 3 --warmups 1
~~~

Repeat without screenshots:

~~~powershell
.\.venv\Scripts\python.exe benchmarks/benchmark_exploration.py --actions 20 --repeats 3 --warmups 1 --no-screenshots
~~~

Increase the captured page size:

~~~powershell
.\.venv\Scripts\python.exe benchmarks/benchmark_exploration.py --actions 50 --repeats 3 --warmups 1 --widgets 300 --properties 12 --states 10
~~~

## Options

| Option | Meaning | Default |
| --- | --- | --- |
| --actions | Browser operations per sample. | 20 |
| --repeats | Measured rounds, each running all three modes. | 3 |
| --warmups | Initial rounds excluded from the median. | 1 |
| --widgets | Additional non-actionable div/span pairs. | 50 |
| --properties | Extra data attributes on each generated div. These add to the adapter's ordinary captured properties. | 4 |
| --states | Page titles visited cyclically, producing distinct states under the default abstraction. | 5 |
| --no-screenshots | Disable screenshot capture in evidence and ASM modes. | Screenshots enabled |
| --existing-trace | Load historical evidence into ASM mode; repeat for several individual trace directories. | None |
| --output | Parent directory for results. | target/benchmarks |

Warm-up rounds let browser and runtime initialization settle before measured rounds. Each sample uses a fresh browser context; mode order rotates between rounds. The browser process is launched once outside sample timing.

## Read the timings

Times are measured with a monotonic clock. Nested work is subtracted from its parent category, so each elapsed interval is counted once.

| Category | Meaning |
| --- | --- |
| startup | Create the context/page, load the local fixture, and initialize recording. |
| model_setup | Create the ASM, including reading supplied historical traces and building its initial model. |
| readiness | Wait for DOMContentLoaded. |
| discovery | Find the currently eligible control in the browser and create its action description. |
| applicability | Recheck that the discovered control is usable and still matches. |
| browser_actions | Execute the native click or fill, including Playwright's waits. |
| dom_capture | Extract and transport DOM data and map it into captured widgets, excluding screenshot time. |
| screenshots | Capture PNG screenshots. |
| recording | Recorder operations, including snapshot copies, action bindings, validation, artifact/event writing, and synchronization; nested capture and browser operations are excluded. |
| model_update | Accept evidence updates, validate them, and update the abstract model. |
| selection | Run ASM selection. |
| coordination | Driver/controller work around the timed operations, including preparing model input and constructing returned results. |
| cleanup | Finish recording and close the browser context. |
| other | Timing-wrapper setup, checks, and remaining sample overhead. |
| total | Elapsed sample time, including cleanup. |

Medians are calculated independently for each category and total, so the displayed median rows need not add up exactly. The Playwright baseline script does not produce evidence or screenshots; their costs appear in the recording modes. Compare the two screenshot settings to assess screenshot overhead.

## Saved results

Each invocation creates a unique directory with:

- fixture.html: generated page used for that run.
- results.json: settings, environment, individual timings, matching action logs, and medians.
- samples.json: completed samples, saved incrementally.
- traces/: evidence traces from both recording modes, including warm-ups.

Trace validation runs outside the measured sample interval and checks event/reference integrity, artifacts, completed executions, recorded transitions, observation counts, and screenshot counts. The benchmark uses local HTTP and makes no requests to ParaBank.

Timing hooks live in this benchmark and are removed after each sample. Production libraries contain no benchmark diagnostics.
