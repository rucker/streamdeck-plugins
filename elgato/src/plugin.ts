/**
 * Claude Sessions for Elgato's Stream Deck app (macOS): the counterpart of the
 * StreamController plugin in com_rucker_ClaudeSessions. Shows the state of
 * every running Claude Code session and jumps to its tmux pane in iTerm2.
 * State comes from the Claude Code hook in ../hooks/claude_deck_hook.py.
 */

import streamDeck from "@elgato/streamdeck";

import { NextWaiting } from "./actions/next-waiting";
import { SessionDial } from "./actions/session-dial";
import { SessionSlot } from "./actions/session-slot";

const actions = [new SessionSlot(), new NextWaiting(), new SessionDial()];
for (const action of actions) {
	streamDeck.actions.registerAction(action);
}

// Ages, blinking and state changes all need a redraw; unchanged frames aren't resent.
setInterval(() => actions.forEach((a) => a.refreshAll()), 1000);

streamDeck.connect();
