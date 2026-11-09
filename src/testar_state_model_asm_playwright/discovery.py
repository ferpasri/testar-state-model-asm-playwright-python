"""Discover executable actions without requiring an exploratory testing tool."""

from dataclasses import dataclass, field
from importlib.resources import files
from typing import Mapping

from playwright.sync_api import Locator, Page


@dataclass(frozen=True)
class BrowserAction:
    """A widget action or browser-history back; input values stay out of descriptions."""

    action_type: str
    name: str
    locator: Locator | None
    value: str | None = field(default=None, repr=False)
    target_signature: str | None = field(default=None, repr=False)
    page: Page | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.action_type not in {"click", "fill", "go_back"}:
            raise ValueError("Supported action types are click, fill, and go_back")
        if self.action_type == "go_back":
            if self.page is None or self.locator is not None:
                raise ValueError("A history-back action requires a page and no widget locator")
        elif self.locator is None:
            raise ValueError("Click and fill actions require a widget locator")
        if self.action_type == "fill" and not isinstance(self.value, str):
            raise ValueError("A fill action requires a string value")

    def applicable(self) -> bool:
        """Check the current GUI before committing to this previously discovered action."""
        if self.action_type == "go_back":
            if self.page.is_closed():
                return False
            return self.page.evaluate("""() => {
                if (window.navigation && typeof window.navigation.canGoBack === "boolean") {
                    return window.navigation.canGoBack;
                }
                return window.history.length > 1;
            }""")
        if not (self.locator.count() == 1 and self.locator.is_visible()
                and self.locator.is_enabled()
                and (self.action_type != "fill" or self.locator.is_editable())):
            return False
        if self.target_signature is not None:
            current = self.locator.evaluate("""element => JSON.stringify([
                element.localName, element.id, element.getAttribute("name"),
                element.getAttribute("type"), element.getAttribute("href"),
                element.getAttribute("aria-label"), element.textContent
            ])""")
            return current == self.target_signature
        return True

    def execute(self, timeout: float):
        """Delegate one selected action to the official Playwright API."""
        if self.action_type == "go_back":
            return self.page.go_back(timeout=timeout, wait_until="domcontentloaded")
        if self.action_type == "fill":
            return self.locator.fill(self.value, timeout=timeout)
        return self.locator.click(timeout=timeout)


@dataclass(frozen=True)
class DiscoveryOptions:
    """Configure discovery boundaries and CSS selectors with explicit input values."""

    input_values: Mapping[str, str] = field(default_factory=dict, repr=False)
    excluded_selectors: tuple[str, ...] = ()
    same_origin_only: bool = True
    max_actions: int = 200

    def __post_init__(self):
        if type(self.max_actions) is not int or not 1 <= self.max_actions <= 5000:
            raise ValueError("max_actions must be between 1 and 5000")
        if type(self.same_origin_only) is not bool:
            raise ValueError("same_origin_only must be a boolean")
        values = dict(self.input_values)
        if any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in values.items()):
            raise ValueError("input_values must map CSS selectors to strings")
        excluded = tuple(self.excluded_selectors)
        if any(not isinstance(selector, str) or not selector for selector in excluded):
            raise ValueError("excluded_selectors must contain CSS selector strings")
        object.__setattr__(self, "input_values", values)
        object.__setattr__(self, "excluded_selectors", excluded)


def discover_actions(page: Page, options: DiscoveryOptions | None = None) -> list[BrowserAction]:
    """Find visible enabled clicks and configured fills in one browser-side discovery call."""
    options = options or DiscoveryOptions()
    script = files(__package__).joinpath("resources/discover.js").read_text(encoding="utf-8")
    discovered = page.evaluate(script, {
        "inputSelectors": list(options.input_values),
        "excluded": list(options.excluded_selectors),
        "sameOrigin": options.same_origin_only,
        "limit": options.max_actions,
    })
    return [
        BrowserAction(item["type"], item["name"], page.locator(item["selector"]),
                      options.input_values[item["inputSelector"]] if item["type"] == "fill" else None,
                      item["signature"])
        for item in discovered
    ]
