/**
 * Recovers a deck the Stream Deck app has given up on. When the Mac wakes with
 * the deck plugged in (e.g. plugged back into a KVM), the app's first command
 * to it can fail ("Read FW version: FAILED"), and the app never retries: the
 * deck keeps its last images until it's replugged. The plugin keeps running,
 * so it watches the app's log for that failure and replugs the deck in
 * software (bin/reenumerate, from native/reenumerate.c), which the app then
 * connects to like any newly plugged-in deck.
 */

import { execFile } from "node:child_process";
import { closeSync, openSync, readSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import streamDeck from "@elgato/streamdeck";

const APP_LOG = join(homedir(), "Library", "Logs", "ElgatoStreamDeck", "StreamDeck.log");
const HELPER = fileURLToPath(new URL("reenumerate", import.meta.url));

// e.g. "Problem with connecting HID device @(1)[4057/132/A00WA6371ID557]: -1": vendor, product, serial.
const FAILED = /Problem with connecting HID device @\(\d+\)\[(\d+)\/(\d+)\/([^\]]+)\]/;

const POLL_MS = 2000;
// Let the deck finish starting up before replugging it.
const SETTLE_MS = 3000;
// Each failed reconnect gets another replug, but only so many per deck.
const MAX_RESETS = 3;
const RESET_WINDOW_MS = 2 * 60_000;

function size(path: string): number {
	try {
		return statSync(path).size;
	} catch {
		return 0;
	}
}

function read(path: string, start: number, end: number): string {
	const fd = openSync(path, "r");
	try {
		const buffer = Buffer.alloc(end - start);
		readSync(fd, buffer, 0, buffer.length, start);
		return buffer.toString("utf8");
	} finally {
		closeSync(fd);
	}
}

export function recoverStuckDecks(log = APP_LOG, helper = HELPER): void {
	// Only failures from now on: an old one was dealt with (or replugged) long ago.
	let offset = size(log);
	let partial = "";
	const resets = new Map<string, number[]>();

	setInterval(() => {
		const end = size(log);
		if (end < offset) {
			// A new log: the app restarted.
			offset = 0;
			partial = "";
		}
		if (end === offset) return;
		const lines = (partial + read(log, offset, end)).split("\n");
		offset = end;
		partial = lines.pop() ?? "";

		for (const line of lines) {
			const match = FAILED.exec(line);
			if (!match) continue;
			const [, vendor, product, serial] = match;
			const now = Date.now();
			const recent = (resets.get(serial) ?? []).filter((t) => now - t < RESET_WINDOW_MS);
			if (recent.length >= MAX_RESETS) {
				streamDeck.logger.warn(`[AgentSessions] deck ${serial} still failing to connect; giving up until it's replugged`);
				continue;
			}
			resets.set(serial, [...recent, now]);
			streamDeck.logger.info(`[AgentSessions] the app couldn't connect to deck ${serial}; replugging it`);
			setTimeout(() => {
				execFile(helper, [vendor, product, serial], { timeout: 10_000 }, (error, _stdout, stderr) => {
					if (error) streamDeck.logger.warn(`[AgentSessions] replugging deck ${serial} failed: ${stderr.trim() || error.message}`);
				});
			}, SETTLE_MS);
		}
	}, POLL_MS);
}
