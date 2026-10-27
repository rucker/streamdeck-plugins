import { type Action, action } from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

import { type Frame, LOGO_EMPTY, meterKeyImage, meterStripImage } from "../render";
import { humanizeUntil, readUsage } from "../usage";
import { ClaudeAction } from "./base";

/** Your plan's 5-hour and weekly usage, with the time until each resets. */
@action({ UUID: "com.rucker.claude-sessions.usage" })
export class UsageMeter extends ClaudeAction {
	protected frameFor(_action: Action<JsonObject>): Frame {
		return { top: "", center: "No usage\nyet", bottom: "", color: null, centerSize: 11, logo: LOGO_EMPTY };
	}

	override refresh(action: Action<JsonObject>): void {
		const windows = readUsage();
		if (!windows) {
			super.refresh(action);
			return;
		}
		// Redraw only when what's visible changes (percentages, or a reset countdown ticking over).
		const key = JSON.stringify(windows.map((w) => [w.label, Math.round(w.percent), humanizeUntil(w.resetsAt)]));
		if (this.shown.get(action.id) === key) return;
		this.shown.set(action.id, key);
		if (action.isKey()) {
			void action.setImage(meterKeyImage(windows));
		} else if (action.isDial()) {
			void action.setFeedback({ canvas: meterStripImage(windows) });
		}
	}

	protected onPress(_action: Action<JsonObject>): void {}
}
