import { type Action, action, type DialRotateEvent } from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

import { type Frame, logoHeader } from "../render";
import { type Session } from "../sessions";
import { ClaudeAction } from "./base";

/** Stream Deck+ dial: turn to pick a session, press/tap to jump, hold to approve. */
@action({ UUID: "com.rucker.claude-sessions.dial" })
export class SessionDial extends ClaudeAction {
	private selectedIds = new Map<string, string>();

	private selected(action: Action<JsonObject>): { index: number; sessions: Session[] } {
		const sessions = this.store.sessions();
		const ids = sessions.map((s) => s.session_id);
		let id = this.selectedIds.get(action.id);
		if (!id || !ids.includes(id)) {
			// Selection vanished (or none yet): default to whoever needs you.
			id = this.store.nextNeedingAttention()?.session_id ?? ids[0];
			if (id) this.selectedIds.set(action.id, id);
		}
		return { index: id ? ids.indexOf(id) : -1, sessions };
	}

	protected frameFor(action: Action<JsonObject>): Frame {
		const { index, sessions } = this.selected(action);
		if (index < 0) {
			return { top: "", center: "", bottom: "No sessions", color: null, logo: logoHeader(false) };
		}
		return this.sessionFrame(action, sessions[index], `${index + 1}/${sessions.length} `);
	}

	override onDialRotate(ev: DialRotateEvent<JsonObject>): void {
		const { index, sessions } = this.selected(ev.action);
		if (index < 0) return;
		const next = (((index + ev.payload.ticks) % sessions.length) + sessions.length) % sessions.length;
		this.selectedIds.set(ev.action.id, sessions[next].session_id);
		this.refresh(ev.action);
	}

	protected async onPress(action: Action<JsonObject>): Promise<void> {
		const { index, sessions } = this.selected(action);
		if (index >= 0) await this.store.jumpTo(sessions[index]);
	}

	protected override async onHold(action: Action<JsonObject>): Promise<void> {
		const { index, sessions } = this.selected(action);
		await this.approve(action, index >= 0 ? sessions[index] : null);
	}
}
