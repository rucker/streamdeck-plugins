"""
Claude Sessions - StreamController plugin

Shows the state of every running Claude Code session (working / your turn /
needs approval) and jumps to its tmux pane on press. State comes from the
Claude Code hook in ../hooks/claude_deck_hook.py.
"""

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

# Relative imports: StreamController imports this as plugins.<folder>.main, and
# a top-level "actions" module would collide with other plugins' actions/ dirs.
from .actions import NextWaiting, SessionDial, SessionSlot
from .sessions import SessionStore


class ClaudeSessionsPlugin(PluginBase):
    def __init__(self):
        super().__init__()

        self.store = SessionStore()

        key_and_dial = {
            Input.Key: ActionInputSupport.SUPPORTED,
            Input.Dial: ActionInputSupport.SUPPORTED,
            Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
        }

        self.add_action_holder(ActionHolder(
            plugin_base=self,
            action_base=SessionSlot,
            action_id_suffix="SessionSlot",
            action_name="Session Slot",
            action_support=key_and_dial,
        ))
        self.add_action_holder(ActionHolder(
            plugin_base=self,
            action_base=NextWaiting,
            action_id_suffix="NextWaiting",
            action_name="Next Waiting Session",
            action_support=key_and_dial,
        ))
        self.add_action_holder(ActionHolder(
            plugin_base=self,
            action_base=SessionDial,
            action_id_suffix="SessionDial",
            action_name="Session Picker (Dial)",
            action_support={
                Input.Key: ActionInputSupport.UNSUPPORTED,
                Input.Dial: ActionInputSupport.SUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
            },
        ))

        self.register(
            plugin_name="Claude Sessions",
            plugin_version="0.1.0",
            app_version="1.5.0-beta",
        )
