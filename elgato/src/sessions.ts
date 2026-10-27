/**
 * Session store and tmux/iTerm2 plumbing shared by all Agent Sessions actions;
 * the macOS counterpart of com_rucker_AgentSessions/sessions.py.
 *
 * The hook (hooks/agent_deck_hook.py at the repo root) writes one JSON file
 * per agent session (Claude Code, Copilot or Grok) into STATE_DIR. Every
 * action redraws once a second, so reads are cached and shared through a
 * single SessionStore.
 */

import { execFile } from "node:child_process";
import { readdirSync, readFileSync, unlinkSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join, normalize } from "node:path";

import streamDeck from "@elgato/streamdeck";

export const STATE_DIR = join(homedir(), ".cache", "agent-deck");

export const WORKING = "working";
export const IDLE = "idle";
export const DONE = "done";
export const PERMISSION = "permission";
export const UNKNOWN = "unknown"; // an agent seen in tmux, but no hook has reported yet
const ATTENTION = [PERMISSION, DONE];

const TERMINAL_BUNDLE_ID = "com.googlecode.iterm2";

const READ_CACHE_MS = 500;
const TMUX_INTERVAL_MS = 1000;
const PRUNE_INTERVAL_MS = 10_000;
// Sessions outside tmux can't be checked for liveness; drop them once they've
// been silent this long in case SessionEnd never fired (crash, kill -9).
const UNTRACKED_MAX_AGE_SECONDS = 12 * 3600;

const SHELLS = new Set(["bash", "zsh", "fish", "sh", "dash"]);

export const CLAUDE = "claude";

/** The agent running in a tmux pane, from #{pane_current_command}. */
function paneAgent(command: string): string | null {
	// Claude Code sets its process title to its version, e.g. "2.1.311".
	if (command === CLAUDE || /^\d+\.\d+\.\d+$/.test(command)) return CLAUDE;
	// Grok's binary is named per platform, e.g. "grok-macos-aarch64" (tmux cuts it short).
	if (command === "grok" || command.startsWith("grok-")) return "grok";
	return command === "copilot" ? command : null;
}

// Each agent's tool permission dialog with "1. Yes" highlighted. "1" answers it
// in both. Copilot's sits in a box, and its folder-trust question ("Do you trust
// the files…") must not match.
const APPROVE_DIALOGS: Record<string, RegExp> = {
	claude: /^\s*❯\s*1\.\s*Yes\s*$(?=[\s\S]*Esc to cancel)/m,
	copilot: /Do you want to [^\n]*\?[\s│]*❯ 1\. Yes[ │]*$(?=[\s\S]*↑\/↓ to navigate · enter to select · esc to cancel)/m,
};

// The Stream Deck app starts plugins with a minimal PATH, which misses Homebrew,
// and no locale, under which tmux prints the tabs in our -F formats as "_".
const ENV = {
	...process.env,
	PATH: ["/opt/homebrew/bin", "/usr/local/bin", process.env.PATH ?? "/usr/bin:/bin"].join(":"),
	LANG: process.env.LANG || "en_US.UTF-8",
};

export type Session = {
	session_id: string;
	agent?: string; // claude (the default), copilot or grok
	cwd?: string;
	project?: string;
	tmux_pane?: string | null;
	started?: number;
	updated?: number;
	state?: string;
	since?: number;
	request?: string;
	request_kind?: string;
};

type Result = { ok: boolean; stdout: string; stderr: string };

function run(command: string, args: string[], timeoutMs = 3000): Promise<Result> {
	return new Promise((resolve) => {
		execFile(command, args, { env: ENV, timeout: timeoutMs }, (error, stdout, stderr) => {
			resolve({ ok: !error, stdout: String(stdout), stderr: String(stderr) });
		});
	});
}

export function projectName(cwd: string | undefined): string {
	// Same naming as the hook's, so a placeholder keeps its label when replaced.
	if (!cwd) return "?";
	const path = normalize(cwd).replace(/\/+$/, "");
	if (path === normalize(homedir()).replace(/\/+$/, "")) return "~";
	return basename(path);
}

/** tmux position of a pane: session (numeric names first, naturally), window, pane. */
type PaneOrder = [number, number, string, number, number];

function compareOrder(a: PaneOrder, b: PaneOrder): number {
	for (let i = 0; i < a.length; i++) {
		if (a[i] < b[i]) return -1;
		if (a[i] > b[i]) return 1;
	}
	return 0;
}

export class SessionStore {
	private sessionsCache: Session[] = [];
	private lastRead = 0;
	private suspects = new Set<string>();
	/** The tmux pane you're looking at: active pane AND iTerm2 frontmost. */
	focusedPane: string | null = null;
	/** pane_id -> its tmux position. */
	private paneOrder = new Map<string, PaneOrder>();
	/** pane_id -> agent and cwd for every tmux pane running an agent, hooked or not. */
	private agentPanes = new Map<string, { agent: string; path: string }>();

	constructor() {
		this.loop(TMUX_INTERVAL_MS, () => this.trackTmux());
		this.loop(PRUNE_INTERVAL_MS, () => this.pruneOnce());
	}

	/** Runs `work` every `intervalMs`, never overlapping itself. */
	private loop(intervalMs: number, work: () => Promise<void>): void {
		const tick = async (): Promise<void> => {
			try {
				await work();
			} catch (e) {
				streamDeck.logger.warn(`[AgentSessions] background task failed: ${e}`);
			}
			setTimeout(tick, intervalMs);
		};
		setTimeout(tick, intervalMs);
	}

	// ------------------------------------------------------------------ //
	// Reading
	// ------------------------------------------------------------------ //

	/**
	 * All known sessions in tmux window order, so keys renumber the way tmux
	 * windows do. Sessions outside tmux (or not yet seen there) go last, by
	 * start time.
	 */
	sessions(): Session[] {
		if (Date.now() - this.lastRead > READ_CACHE_MS) {
			this.sessionsCache = this.readAll();
			this.lastRead = Date.now();
		}
		const all = [...this.sessionsCache, ...this.unhookedSessions(this.sessionsCache)];
		return all.sort((a, b) => {
			const oa = a.tmux_pane ? this.paneOrder.get(a.tmux_pane) : undefined;
			const ob = b.tmux_pane ? this.paneOrder.get(b.tmux_pane) : undefined;
			if (oa && ob) return compareOrder(oa, ob);
			if (oa || ob) return oa ? -1 : 1;
			return (a.started ?? 0) - (b.started ?? 0) || a.session_id.localeCompare(b.session_id);
		});
	}

	/**
	 * Placeholders for agent panes with no state file yet, e.g. sessions
	 * started before the hooks were installed that haven't fired one since.
	 * Replaced by the real record as soon as that session triggers a hook.
	 */
	private unhookedSessions(hooked: Session[]): Session[] {
		const known = new Set(hooked.map((s) => s.tmux_pane));
		return [...this.agentPanes]
			.filter(([pane]) => !known.has(pane))
			.map(([pane, { agent, path }]) => ({
				session_id: `tmux:${pane}`,
				agent,
				tmux_pane: pane,
				project: projectName(path),
				state: UNKNOWN,
				started: 0,
			}));
	}

	private readAll(): Session[] {
		let names: string[];
		try {
			names = readdirSync(STATE_DIR);
		} catch {
			return [];
		}
		const records: Session[] = [];
		for (const name of names) {
			if (!name.endsWith(".json") || name.startsWith(".")) continue;
			try {
				records.push(JSON.parse(readFileSync(join(STATE_DIR, name), "utf8")));
			} catch {
				// mid-write or removed; picked up next tick
			}
		}
		return records;
	}

	isWatched(session: Session): boolean {
		return !!session.tmux_pane && session.tmux_pane === this.focusedPane;
	}

	/** Waiting on you, and you're not already looking at it. */
	needsAttention(session: Session): boolean {
		return ATTENTION.includes(session.state ?? "") && !this.isWatched(session);
	}

	/** Longest-waiting permission prompt first, then longest-waiting finished turn. */
	nextNeedingAttention(): Session | null {
		for (const state of ATTENTION) {
			const waiting = this.sessions().filter((s) => s.state === state && this.needsAttention(s));
			if (waiting.length) {
				return waiting.reduce((a, b) => ((b.since ?? 0) < (a.since ?? 0) ? b : a));
			}
		}
		return null;
	}

	invalidate(): void {
		this.lastRead = 0;
	}

	// ------------------------------------------------------------------ //
	// Tracking tmux layout and which pane you're looking at
	// ------------------------------------------------------------------ //

	private async trackTmux(): Promise<void> {
		await this.readTmuxPanes();
		try {
			this.focusedPane = await this.readFocusedPane();
		} catch {
			this.focusedPane = null;
		}
	}

	private async readTmuxPanes(): Promise<void> {
		const result = await run("tmux", [
			"list-panes", "-a", "-F",
			["#{pane_id}", "#{session_name}", "#{window_index}", "#{pane_index}",
				"#{pane_current_command}", "#{pane_current_path}"].join("\t"),
		]);
		if (!result.ok) {
			this.paneOrder = new Map();
			this.agentPanes = new Map();
			return;
		}
		const order = new Map<string, PaneOrder>();
		const agents = new Map<string, { agent: string; path: string }>();
		for (const line of result.stdout.split("\n")) {
			const [paneId, session, window, pane, command, ...path] = line.split("\t");
			if (command === undefined) continue;
			// Session "10" sorts after "2", like tmux's own ordering.
			const numeric = /^\d+$/.test(session);
			order.set(paneId, [numeric ? 0 : 1, numeric ? Number(session) : 0, numeric ? "" : session,
				Number(window), Number(pane)]);
			const agent = paneAgent(command);
			if (agent) agents.set(paneId, { agent, path: path.join("\t") });
		}
		this.paneOrder = order;
		this.agentPanes = agents;
	}

	private async readFocusedPane(): Promise<string | null> {
		if (!(await this.terminalIsFrontmost())) return null;
		// Run outside tmux, display-message reports the most recently used client.
		const result = await run("tmux", ["display-message", "-p", "#{pane_id}"]);
		return result.ok ? result.stdout.trim() || null : null;
	}

	/** lsappinfo needs no Automation/Accessibility permission, unlike osascript. */
	private async terminalIsFrontmost(): Promise<boolean> {
		const front = await run("lsappinfo", ["front"]);
		if (!front.ok || !front.stdout.trim()) return false;
		const info = await run("lsappinfo", ["info", "-only", "bundleid", front.stdout.trim()]);
		return info.ok && info.stdout.includes(`"${TERMINAL_BUNDLE_ID}"`);
	}

	// ------------------------------------------------------------------ //
	// Pruning sessions whose agent process is gone
	// ------------------------------------------------------------------ //

	private async pruneOnce(): Promise<void> {
		const result = await run("tmux", ["list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}"]);
		const panes = new Map<string, string>();
		if (result.ok) {
			for (const line of result.stdout.split("\n")) {
				const space = line.indexOf(" ");
				if (space > 0) panes.set(line.slice(0, space), line.slice(space + 1));
			}
		}

		const now = Date.now() / 1000;
		const suspects = new Set<string>();
		for (const session of this.readAll()) {
			const pane = session.tmux_pane;
			const dead = pane && result.ok
				// Pane closed, or the agent exited back to the shell without SessionEnd.
				? !panes.has(pane) || SHELLS.has(panes.get(pane) ?? "")
				: now - (session.updated ?? now) > UNTRACKED_MAX_AGE_SECONDS;
			if (!dead) continue;
			// Require two consecutive dead sightings so a momentary blip
			// (e.g. a foreground shell command) doesn't drop a live session.
			if (this.suspects.has(session.session_id)) {
				this.remove(session);
			} else {
				suspects.add(session.session_id);
			}
		}
		this.suspects = suspects;
	}

	private remove(session: Session): void {
		try {
			unlinkSync(join(STATE_DIR, `${session.session_id}.json`));
		} catch {
			// already gone
		}
		this.invalidate();
	}

	// ------------------------------------------------------------------ //
	// Jumping to a session
	// ------------------------------------------------------------------ //

	async jumpTo(session: Session): Promise<void> {
		const pane = session.tmux_pane;
		if (pane) {
			// switch-client handles panes in another tmux session; the other two
			// make the pane current within its window/session.
			const result = await run("tmux", [
				"switch-client", "-t", pane, ";",
				"select-window", "-t", pane, ";",
				"select-pane", "-t", pane,
			]);
			if (!result.ok) {
				streamDeck.logger.warn(`[AgentSessions] tmux jump to ${pane} failed: ${result.stderr.trim()}`);
			}
		}
		const raised = await run("open", ["-b", TERMINAL_BUNDLE_ID]);
		if (!raised.ok) {
			streamDeck.logger.warn(`[AgentSessions] could not raise iTerm2: ${raised.stderr.trim()}`);
		}
	}

	// ------------------------------------------------------------------ //
	// Approving a permission prompt
	// ------------------------------------------------------------------ //

	static canApprove(session: Session | null): session is Session {
		return !!session && session.state === PERMISSION && session.request_kind === "tool" && !!session.tmux_pane;
	}

	/** Answers "1. Yes" (never "don't ask again"). */
	async approve(session: Session): Promise<boolean> {
		if (!SessionStore.canApprove(session)) return false;
		const pane = session.tmux_pane!;
		// Check the dialog is really on screen: it may have been answered in the
		// terminal already, and a stray "1" would land in the prompt instead.
		const screen = await run("tmux", ["capture-pane", "-p", "-t", pane]);
		const dialog = APPROVE_DIALOGS[session.agent ?? CLAUDE];
		if (!screen.ok || !dialog?.test(screen.stdout)) {
			streamDeck.logger.info(`[AgentSessions] no approval dialog visible in ${pane}; not sending`);
			return false;
		}
		return (await run("tmux", ["send-keys", "-t", pane, "1"])).ok;
	}
}

export const store = new SessionStore();
