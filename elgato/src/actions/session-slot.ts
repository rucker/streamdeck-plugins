import { type Action, action } from "@elgato/streamdeck";

import { type Frame } from "../render";
import { type Session } from "../sessions";
import { AgentAction } from "./base";

type SlotSettings = {
	slot?: number | string; // the settings dropdown stores strings
};

/** Reading order on the deck: keys row by row, then dials left to right. */
function position(action: Action<SlotSettings>): [number, number, number] | null {
	if (action.isKey()) {
		const c = action.coordinates;
		return c ? [0, c.row, c.column] : null; // no coordinates inside a multi-action
	}
	if (action.isDial()) {
		return [1, 0, action.coordinates.column];
	}
	return null;
}

function compare(a: number[], b: number[]): number {
	for (let i = 0; i < a.length; i++) {
		if (a[i] !== b[i]) return a[i] - b[i];
	}
	return 0;
}

/** Shows the Nth active agent session; press to jump, hold to approve. */
@action({ UUID: "com.rucker.agent-sessions.slot" })
export class SessionSlot extends AgentAction<SlotSettings> {
	/** Manual slot number, or 0 for automatic (numbered by position on the page). */
	private slot(action: Action<SlotSettings>): number {
		return Number(this.settings.get(action.id)?.slot ?? 0) || 0;
	}

	private session(action: Action<SlotSettings>): Session | null {
		const sessions = this.store.sessions();
		const slot = this.slot(action);
		const index = slot ? slot - 1 : this.autoIndex(action, sessions.length);
		return index !== null && index >= 0 && index < sessions.length ? sessions[index] : null;
	}

	/**
	 * Automatic slots number themselves left-to-right, top-to-bottom (keys,
	 * then dials), skipping sessions that manually numbered slots claim.
	 */
	private autoIndex(action: Action<SlotSettings>, sessionCount: number): number | null {
		const mine = position(action);
		if (!mine) return null;
		const onDevice = this.actions.filter((a) => a.device.id === action.device.id).toArray();
		const manual = new Set(onDevice.map((a) => this.slot(a)).filter(Boolean));
		const autoPositions = onDevice
			.filter((a) => !this.slot(a))
			.map(position)
			.filter((p): p is [number, number, number] => p !== null)
			.sort(compare);
		const free = [...Array(sessionCount).keys()].filter((i) => !manual.has(i + 1));
		const rank = autoPositions.findIndex((p) => compare(p, mine) === 0);
		return rank >= 0 && rank < free.length ? free[rank] : null;
	}

	protected frameFor(action: Action<SlotSettings>): Frame {
		return this.sessionFrame(action, this.session(action));
	}

	protected async onPress(action: Action<SlotSettings>): Promise<void> {
		const session = this.session(action);
		if (session) await this.store.jumpTo(session);
	}

	protected override async onHold(action: Action<SlotSettings>): Promise<void> {
		await this.approve(action, this.session(action));
	}
}
