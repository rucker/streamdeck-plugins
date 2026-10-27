"""
Resume Fix - StreamController plugin

After suspend, StreamController (with "Use new resume mode (beta)" off)
detects the resume, opens the deck again and reloads the page, but the deck
can stay dark until StreamController is restarted. A restart works because
startup USB-resets the deck first; resume doesn't, and it leaves the old
handle open.

This wraps DeckManager.on_resumed (an internal, not plugin API) to do what
startup does first: close the old handles and USB-reset the deck. Then the
stock resume code reopens it and reloads the page.
"""

from loguru import logger as log

from src.backend.DeckManagement.DeckManager import DeckManager
from src.backend.PluginManager.PluginBase import PluginBase


class ResumeFixPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        install_hook()
        self.register(
            plugin_name="Resume Fix",
            plugin_version="0.1.0",
            app_version="1.5.0-beta",
        )


def install_hook():
    original = DeckManager.on_resumed
    if getattr(original, "_resume_fix", False):
        return  # already installed (plugin reloaded)

    def on_resumed(manager):
        try:
            log.info("Resume Fix: closing and USB-resetting decks before reload")
            for controller in manager.deck_controller:
                try:
                    controller.deck.close()
                except Exception:  # noqa: BLE001 - already gone is fine
                    pass
            manager.reset_all_decks()
        except Exception:  # noqa: BLE001 - fall back to the stock behavior
            log.exception("Resume Fix: reset failed")
        original(manager)

    on_resumed._resume_fix = True
    # DetectResumeThread calls deck_manager.on_resumed(), so it picks this up.
    DeckManager.on_resumed = on_resumed
