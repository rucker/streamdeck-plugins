import { type Action, action } from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

import { type Frame, logoHeader } from "../render";
import { IDLE } from "../sessions";
import { COLORS, AgentAction, stateColor, truncate } from "./base";

/**
 * Shows how many sessions need you; press to jump to the one that has waited
 * longest (permission prompts first).
 */
@action({ UUID: "com.rucker.claude-sessions.next-waiting" })
export class NextWaiting extends AgentAction {
	protected frameFor(_action: Action<JsonObject>): Frame {
		const sessions = this.store.sessions();
		const waiting = sessions.filter((s) => this.store.needsAttention(s));
		const target = this.store.nextNeedingAttention();

		if (!sessions.length) {
			return { top: "", center: "", bottom: "No sessions", color: null, logo: logoHeader(false) };
		}
		if (!waiting.length || !target) {
			return { top: "", center: "0", bottom: "None waiting", color: COLORS[IDLE], centerSize: 22, logo: logoHeader(false) };
		}
		return {
			top: "",
			center: String(waiting.length),
			bottom: "→ " + truncate(target.project ?? "?", 8),
			color: stateColor(target.state),
			centerSize: 22,
			logo: logoHeader(true),
		};
	}

	protected async onPress(_action: Action<JsonObject>): Promise<void> {
		const target = this.store.nextNeedingAttention();
		if (target) await this.store.jumpTo(target);
	}
}
