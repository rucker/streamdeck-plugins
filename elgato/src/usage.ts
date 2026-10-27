/**
 * Your plan's usage limits (5-hour and weekly), as recorded by the status line
 * command in ../hooks/agent_deck_statusline.py; the macOS counterpart of
 * com_rucker_AgentSessions/usage.py.
 *
 * The numbers are what Claude Code last heard from the API, so they only move
 * while a Claude Code session is talking to it.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import type { RGB } from "./render";

// Outside ~/.cache/agent-deck/ on purpose: every .json file there is a session.
export const USAGE_FILE = join(homedir(), ".cache", "agent-deck-usage.json");

export const USAGE_OK: RGB = [120, 140, 93];
export const USAGE_WARN: RGB = [217, 119, 87];
export const USAGE_CRIT: RGB = [190, 35, 35];

export type UsageWindow = {
	label: string;
	percent: number;
	resetsAt: number | null; // null once the window has reset (nothing used yet)
};

type RawWindow = { used_percentage?: unknown; resets_at?: unknown };

/** The 5-hour and weekly windows, or null if nothing has been recorded. */
export function readUsage(): [UsageWindow, UsageWindow] | null {
	let data: Record<string, unknown>;
	try {
		data = JSON.parse(readFileSync(USAGE_FILE, "utf8"));
	} catch {
		return null;
	}
	if (!data || typeof data !== "object") return null;
	return [window(data.five_hour as RawWindow, "5h"), window(data.seven_day as RawWindow, "Week")];
}

function window(raw: RawWindow | undefined, label: string): UsageWindow {
	if (!raw || typeof raw !== "object") return { label, percent: 0, resetsAt: null };
	const resetsAt = typeof raw.resets_at === "number" ? raw.resets_at : null;
	if (resetsAt !== null && resetsAt <= Date.now() / 1000) {
		return { label, percent: 0, resetsAt: null }; // reset since it was recorded
	}
	const percent = Number(raw.used_percentage ?? 0);
	return { label, percent: Number.isFinite(percent) ? percent : 0, resetsAt };
}

export function usageColor(percent: number): RGB {
	if (percent >= 90) return USAGE_CRIT;
	if (percent >= 70) return USAGE_WARN;
	return USAGE_OK;
}

export function humanizeUntil(epoch: number | null): string {
	if (epoch === null) return "";
	const seconds = Math.max(0, Math.floor(epoch - Date.now() / 1000));
	const days = Math.floor(seconds / 86400);
	const hours = Math.floor((seconds % 86400) / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	if (days) return `${days}d ${hours}h`;
	if (hours) return `${hours}h ${minutes}m`;
	return `${minutes}m`;
}
