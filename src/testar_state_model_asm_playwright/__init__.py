"""Add action discovery and model-based exploration to synchronous Playwright."""
from .discovery import BrowserAction, DiscoveryOptions, discover_actions
from .driver import PlaywrightExplorationDriver
from .exploration import ExplorationResult, PlaywrightExploration, default_configuration, explore

__all__ = [
    "BrowserAction", "DiscoveryOptions", "discover_actions", "PlaywrightExplorationDriver",
    "ExplorationResult", "PlaywrightExploration", "default_configuration", "explore",
]
