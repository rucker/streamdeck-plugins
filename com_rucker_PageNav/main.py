"""
Page Nav - StreamController plugin

Swipe the Stream Deck+ touch strip to change pages, on every page, with
nothing to set up per page: swipe left for the next page, right for the
previous one (like Elgato's own software). Pages follow the Page Manager's
order and wrap around.

StreamController has no global inputs, so this wraps DeckController's touch
strip callback (an internal, not plugin API). Swipes never reach the page's
own touch strip action; taps still do.
"""

import threading

from loguru import logger as log
from StreamDeck.Devices.StreamDeck import TouchscreenEventType

import globals as gl
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.PluginBase import PluginBase


class PageNavPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        install_hook()
        self.register(
            plugin_name="Page Nav",
            plugin_version="0.1.0",
            app_version="1.5.0-beta",
        )


def install_hook():
    original = DeckController.touchscreen_event_callback
    if getattr(original, "_page_nav", False):
        return  # already installed (plugin reloaded)

    def touchscreen_event_callback(controller, deck, event_type, value, *args, **kwargs):
        try:
            if _handle(controller, event_type, value):
                return
        except Exception:  # noqa: BLE001 - never break the deck's input
            log.exception("Page Nav: touch strip hook failed")
        original(controller, deck, event_type, value, *args, **kwargs)

    touchscreen_event_callback._page_nav = True
    DeckController.touchscreen_event_callback = touchscreen_event_callback

    # Decks already open registered the old bound method; new decks and resume
    # (DeckManager.on_resumed) look it up again and get ours.
    for controller in gl.deck_manager.deck_controller if gl.deck_manager else []:
        controller.deck.set_touchscreen_callback(controller.touchscreen_event_callback)


def _handle(controller, event_type, value) -> bool:
    """True if the event is ours and must not reach the page."""
    if event_type != TouchscreenEventType.DRAG:
        return False
    if not controller.allow_interaction or controller.screen_saver.showing:
        return False  # let the swipe wake the deck instead

    # Same direction logic as ControllerTouchScreen, in logical coordinates.
    value = controller.deck.touch_value_to_logical(value)
    strip = controller.get_input(Input.Touchscreen("sd-plus"))
    if strip is not None and strip.dials_stack_vertically():
        towards_start = value["y"] > value["y_out"]
    else:
        towards_start = value["x"] > value["x_out"]

    # Swiping left pulls in the next page, as on a phone.
    step = 1 if towards_start else -1
    # Off the device's reader thread, like the Deck plugin's Change Page.
    threading.Thread(target=_switch_page, args=(controller, step), daemon=True,
                     name="PageNav").start()
    return True


def _switch_page(controller, step: int):
    pages = gl.page_manager.get_pages()
    if not pages:
        return
    current = controller.active_page.json_path if controller.active_page else None
    index = pages.index(current) if current in pages else -1
    target = pages[(index + step) % len(pages)]
    controller.load_page(gl.page_manager.get_page(target, deck_controller=controller))
