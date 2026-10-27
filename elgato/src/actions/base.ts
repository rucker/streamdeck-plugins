import {
	type Action,
	type DialDownEvent,
	type DialUpEvent,
	type DidReceiveSettingsEvent,
	type KeyDownEvent,
	type KeyUpEvent,
	SingletonAction,
	type TouchTapEvent,
	type WillAppearEvent,
	type WillDisappearEvent,
} from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

import { type Frame, keyImage, LOGO_EMPTY, type RGB, stripImage } from "../render";
import { CLAUDE, DONE, IDLE, PERMISSION, type Session, SessionStore, store, UNKNOWN, WORKING } from "../sessions";

export const COLORS: Record<string, RGB> = {
	[WORKING]: [37, 84, 160],
	[IDLE]: [55, 55, 55],
	[UNKNOWN]: [55, 55, 55],
	[DONE]: [217, 119, 87],
	[PERMISSION]: [190, 35, 35],
};

const STATE_TEXT: Record<string, string> = {
	[WORKING]: "Working",
	[IDLE]: "Ready",
	[UNKNOWN]: "No status",
	[DONE]: "Your turn",
	[PERMISSION]: "APPROVE",
};

// Short press jumps; a long press approves. Like StreamController's default
// hold time, and jumping fires on release so a long press doesn't also jump.
const HOLD_MS = 500;

export function stateColor(state: string | undefined, blink = true): RGB {
	const color = COLORS[state ?? IDLE] ?? COLORS[IDLE];
	// Only a blocked permission prompt pulses; a finished turn can wait.
	if (blink && state === PERMISSION && Math.floor(Date.now() / 1000) % 2) {
		return color.map((c) => Math.floor(c / 2)) as RGB;
	}
	return color;
}

export function truncate(text: string, length: number): string {
	return text.length <= length ? text : text.slice(0, length - 1) + "…";
}

/** Greedy word wrap into at most `lines` lines, breaking long words. */
export function wrap(text: string, width: number, lines: number): string {
	const out: string[] = [];
	let line = "";
	for (let word of text.split(/\s+/).filter(Boolean)) {
		while (word.length > width) {
			if (line) {
				out.push(line);
				line = "";
			}
			out.push(word.slice(0, width));
			word = word.slice(width);
		}
		if (!line) line = word;
		else if (line.length + 1 + word.length <= width) line += " " + word;
		else {
			out.push(line);
			line = word;
		}
	}
	if (line || !out.length) out.push(line);
	if (out.length > lines) {
		return [...out.slice(0, lines - 1), truncate(out.slice(lines - 1).join(" "), width)].join("\n");
	}
	return out.join("\n");
}

/**
 * Shared behavior: redraws every second (only pushing changes to the deck),
 * and turns key/dial presses into press (on short release) and hold events.
 */
export abstract class AgentAction<T extends JsonObject = JsonObject> extends SingletonAction<T> {
	protected store = store;
	protected settings = new Map<string, T>();
	protected shown = new Map<string, string>();
	private holds = new Map<string, { timer: NodeJS.Timeout; fired: boolean }>();

	protected abstract frameFor(action: Action<T>): Frame;
	protected abstract onPress(action: Action<T>): void | Promise<void>;
	protected onHold(_action: Action<T>): void | Promise<void> {}

	override onWillAppear(ev: WillAppearEvent<T>): void {
		this.settings.set(ev.action.id, ev.payload.settings);
		this.shown.delete(ev.action.id);
		this.refreshAll();
	}

	override onWillDisappear(ev: WillDisappearEvent<T>): void {
		this.settings.delete(ev.action.id);
		this.shown.delete(ev.action.id);
		clearTimeout(this.holds.get(ev.action.id)?.timer);
		this.holds.delete(ev.action.id);
		this.refreshAll();
	}

	override onDidReceiveSettings(ev: DidReceiveSettingsEvent<T>): void {
		this.settings.set(ev.action.id, ev.payload.settings);
		this.shown.delete(ev.action.id);
		this.refreshAll();
	}

	refreshAll(): void {
		for (const action of this.actions) {
			this.refresh(action);
		}
	}

	refresh(action: Action<T>): void {
		const frame = this.frameFor(action);
		const key = JSON.stringify(frame);
		if (this.shown.get(action.id) === key) return;
		this.shown.set(action.id, key);
		if (action.isKey()) {
			void action.setImage(keyImage(frame));
		} else if (action.isDial()) {
			void action.setFeedback({ canvas: stripImage(frame) });
		}
	}

	// ------------------------------------------------------------------ //
	// Press vs. hold
	// ------------------------------------------------------------------ //

	override onKeyDown(ev: KeyDownEvent<T>): void {
		this.pressStarted(ev.action);
	}

	override onKeyUp(ev: KeyUpEvent<T>): void {
		this.pressEnded(ev.action);
	}

	override onDialDown(ev: DialDownEvent<T>): void {
		this.pressStarted(ev.action);
	}

	override onDialUp(ev: DialUpEvent<T>): void {
		this.pressEnded(ev.action);
	}

	override onTouchTap(ev: TouchTapEvent<T>): void {
		void (ev.payload.hold ? this.onHold(ev.action) : this.onPress(ev.action));
	}

	private pressStarted(action: Action<T>): void {
		clearTimeout(this.holds.get(action.id)?.timer);
		const hold = {
			fired: false,
			timer: setTimeout(() => {
				hold.fired = true;
				void this.onHold(action);
			}, HOLD_MS),
		};
		this.holds.set(action.id, hold);
	}

	private pressEnded(action: Action<T>): void {
		const hold = this.holds.get(action.id);
		this.holds.delete(action.id);
		if (!hold) return;
		clearTimeout(hold.timer);
		if (!hold.fired) void this.onPress(action);
	}

	// ------------------------------------------------------------------ //
	// Shared session rendering and approval
	// ------------------------------------------------------------------ //

	protected sessionFrame(action: Action<T>, session: Session | null, topPrefix = ""): Frame {
		if (!session) {
			return { top: topPrefix, center: "", bottom: "", color: null, logo: LOGO_EMPTY };
		}
		const state = session.state ?? IDLE;
		let center = STATE_TEXT[state] ?? state;
		let centerSize = 14;
		// A dial's strip segment is wide enough to show what's being asked.
		if (state === PERMISSION && session.request && action.isDial()) {
			center = wrap(session.request, 22, 2);
			centerSize = 11;
		}
		return {
			top: topPrefix + truncate(session.project ?? "?", 10),
			center,
			bottom: "",
			// No pulsing for the session you're already looking at.
			color: stateColor(state, !this.store.isWatched(session)),
			centerSize,
			agent: session.agent ?? CLAUDE,
		};
	}

	protected async approve(action: Action<T>, session: Session | null): Promise<void> {
		const ok = SessionStore.canApprove(session) && (await this.store.approve(session));
		if (!ok && (action.isKey() || action.isDial())) {
			await action.showAlert();
		}
		this.store.invalidate();
	}
}
