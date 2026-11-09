# Implementation specification

## Exploration cycle

The integration implements the ASM library's exploration driver. Observation waits for the configured readiness callback, captures the page, derives actions, applies the action filter, and records eligible available actions. A saved observation and those action bindings are supplied to the ASM.

Before execution, the driver checks that the selected locator still identifies one visible, enabled control. Fill actions also require an editable field. Default-discovery actions also compare the control description with the discovered one, so a different control at the same DOM path requests a refresh. If the control is no longer applicable, it requests a fresh observation without recording an execution.

The evidence adapter allocates and records the selected execution. The driver performs the browser operation, records its outcome, waits for readiness, and captures the resulting state with its available actions. That observation updates the ASM and is reused for the next selection. The initial observation plus one result observation per executed action forms the ordinary exploration trace.

Playwright operation errors are recorded as failed executions. The resulting page is reassessed when available. Unexpected discovery, readiness, or evidence-writing errors propagate to the caller. An outstanding execution remains available through the ASM for investigation.

## Action discovery

Default discovery inspects the main document using one browser-side call. It offers clicks on visible enabled buttons, links, checkbox/radio inputs, and explicit button/link roles. Text inputs and textareas receive fill actions only when their CSS selector has a configured string value. Input values are kept out of action descriptions and object representations. The evidence adapter applies its password-parameter redaction policy.

Hidden, disabled, inert, excluded, and readonly fill targets are omitted. Links use HTTP or HTTPS, remain in the current browsing context, and stay on the same origin by default. Download links are omitted. The configured action limit bounds the discovered list; available-action scope is eligible. This scope describes the reported set and does not claim all possible application actions were discovered.

Locators use main-document element paths without adding attributes to the SUT. Applicability is rechecked before invocation; this does not make DOM capture, discovery, and execution atomic. Playwright performs its own actionability checks during execution.

Default discovery covers the main document. Custom discovery can supply BrowserAction values with native Playwright locators. Frame and shadow-root targets need corresponding evidence capture support to participate in model matching.

## Pages without eligible actions

state_without_actions defaults to go_back: when no eligible widget actions remain and backward navigation is available, the driver offers a browser-history back action. It passes through the action filter and the configured ASM like other available actions. The action is recorded with type go_back and no widget target, and its execution consumes the normal ASM action count. The resulting state is captured normally.

With state_without_actions set to stop, an empty eligible-action set ends exploration normally. Without backward history, go_back also ends exploration. A sequence runner can then start its next sequence.

A target-free back action may be unmatched under target-based abstraction. The default configuration can select it through Random fallback. A custom ASM configuration must permit its selection, for example through Random or Unvisited's observation-local unmatched-choice policy. The driver does not bypass the ASM or invent a widget target.

A custom readiness callback runs before capture and action discovery. If it requires an element absent from the current page, it can time out before the empty-state policy is reached. Readiness errors propagate to the caller. The default waits for DOMContentLoaded without requiring application-specific elements.

## Configuration and extension points

- DiscoveryOptions selects input values, excluded CSS selectors, same-origin link policy, and the maximum discovered action count.
- discover(page, options) replaces the discovery function.
- allow_action(action) filters its output.
- wait_until_ready(page) defines when the page is ready to observe. The default waits for DOMContentLoaded; application-specific asynchronous work may need a different callback.
- action_timeout bounds each selected Playwright operation.
- state_without_actions selects go_back (default) or stop for states without eligible widget actions.
- historical_traces loads existing evidence through the evidence reader before exploration begins.
- configuration supplies abstraction and ASM/controller settings through the shared ASM contract.

The default abstraction compares page address/title and action target identity, using captured ID, name, or DOM path. It retains URL query and session data. Applications with multiple distinct views at the same address/title or dynamic identifiers should supply appropriate abstraction rules.

## Ownership and evidence

PlaywrightExploration owns only recorders it creates. Closing it finishes an owned trace, leaving the page and browser open. Supplied recorders and evidence-facade recorders stay under their original owner's control.

The driver uses the evidence adapter's public capture, available-action, commit, recorded-evidence, and selected-execution APIs. Nested facade recording is suppressed during ASM execution, preserving one action execution per selection. Recordings remain concrete; the abstract model is returned separately for inspection or further selection.

The module uses synchronous Playwright on its owning thread and explores one supplied page. A convenience call returns ExplorationResult with stopped, model, and evidence_directory. PlaywrightExploration exposes its AsmRun for cancellation and inspection between calls.

Selection and lifecycle behavior follow [ASM Specs](https://github.com/ferpasri/testar-state-model-asm-specs). The evidence adapter and abstraction library retain ownership of their respective recording and matching behavior.
