import { type Action, action } from "@elgato/streamdeck";
import type { JsonObject } from "@elgato/utils";

import { type Frame, logoHeader, type RGB } from "../render";
import { DEMO_SESSION } from "../sessions";
import { AgentAction } from "./base";

const DEMO_ON: RGB = [46, 125, 50];

/**
 * Press to start a demo: a tmux session of agents doing small tasks, some of
 * which ask for approval. While it runs, press to jump to it; hold to stop it.
 */
@action({ UUID: "com.rucker.agent-sessions.demo" })
export class DemoMode extends AgentAction {
	protected frameFor(_action: Action<JsonObject>): Frame {
		const logo = logoHeader(false);
		if (this.store.demoStopping) {
			return { top: "", center: "Stopping…", bottom: "", color: DEMO_ON, logo };
		}
		if (this.store.demoRunning()) {
			return { top: "", center: "Demo on", bottom: "Hold to stop", color: DEMO_ON, logo };
		}
		if (this.store.demoStarting) {
			return { top: "", center: "Starting…", bottom: "", color: null, logo };
		}
		return { top: "", center: "Demo", bottom: "Press to start", color: null, logo };
	}

	protected async onPress(action: Action<JsonObject>): Promise<void> {
		if (this.store.demoRunning()) {
			await this.store.jumpToTarget(`${DEMO_SESSION}:`);
			return;
		}
		if (this.store.demoStarting) return;
		this.store.demoStarting = true;
		this.refreshAll();
		const ok = await this.store.runDemo("start");
		this.store.demoStarting = false;
		if (!ok && action.isKey()) await action.showAlert();
		this.refreshAll();
	}

	protected override async onHold(action: Action<JsonObject>): Promise<void> {
		if (!this.store.demoRunning() || this.store.demoStopping) return;
		this.store.demoStopping = true;
		this.refreshAll();
		const ok = await this.store.runDemo("stop");
		this.store.demoStopping = false;
		if (!ok && action.isKey()) await action.showAlert();
		this.refreshAll();
	}
}
