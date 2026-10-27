/**
 * Draws keys (144×144) and touch strip segments (200×100) as SVG, mirroring
 * how the StreamController plugin lays out its labels and logo.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { humanizeUntil, usageColor, type UsageWindow } from "./usage";

export const CLAUDE_ORANGE: RGB = [217, 119, 87];
export const CLAUDE_CREAM: RGB = [250, 249, 245];

export type RGB = [number, number, number];

// Ray lengths (fraction of the radius), deliberately uneven so it reads as a
// hand-drawn spark rather than a mechanical asterisk. Same as logo.py.
const RAYS = [1.0, 0.78, 0.92, 0.7, 0.96, 0.82, 0.88, 0.72, 0.98, 0.76, 0.9, 0.8];

const FONT = "Helvetica Neue, Helvetica, Arial, sans-serif";

export type Logo = {
	size: number; // fraction of the canvas height
	valign: number; // -1 top, 0 middle, 1 bottom
	halign?: number; // -1 left, 0 center, 1 right
	opacity?: number;
	tint?: RGB;
};

/** Faded and centered on keys with nothing to show, so they look intentional. */
export const LOGO_EMPTY: Logo = { size: 0.55, valign: 0, opacity: 0.25 };

/** Small logo at the top; cream on orange/red keys, where orange would vanish. */
export function logoHeader(onColor: boolean): Logo {
	return { size: 0.36, valign: -0.96, tint: onColor ? CLAUDE_CREAM : undefined };
}

export type Frame = {
	top: string;
	center: string;
	bottom: string;
	color: RGB | null; // null = black (empty)
	centerSize?: number; // in StreamController's key-label points (14 = normal)
	logo?: Logo;
	agent?: string; // session keys: that agent's logo in a corner badge
};

/** The spark in a 100×100 box: blunt, slightly tapered rays with round caps. */
function spark(fill: string): string {
	const c = 50;
	const radius = 44;
	const rootHalf = 5;
	const tipHalf = 3.2;
	const parts = RAYS.map((length, i) => {
		const angle = (2 * Math.PI * i) / RAYS.length - Math.PI / 2;
		const tip = radius * length - tipHalf;
		const [dx, dy] = [Math.cos(angle), Math.sin(angle)];
		const [px, py] = [-dy, dx];
		const [tx, ty] = [c + dx * tip, c + dy * tip];
		const points = [
			[c + px * rootHalf, c + py * rootHalf],
			[tx + px * tipHalf, ty + py * tipHalf],
			[tx - px * tipHalf, ty - py * tipHalf],
			[c - px * rootHalf, c - py * rootHalf],
		].map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
		return `<polygon points="${points}"/><circle cx="${tx.toFixed(2)}" cy="${ty.toFixed(2)}" r="${tipHalf}"/>`;
	});
	return `<g fill="${fill}">${parts.join("")}<circle cx="${c}" cy="${c}" r="10"/></g>`;
}

const AGENT_LOGOS = fileURLToPath(new URL("../imgs/agents/", import.meta.url));
const agentLogos = new Map<string, string | null>();

/** An agent's logo (imgs/agents/<agent>.svg) as markup for a 24×24 box, or null if there's none. */
function agentLogo(agent: string): string | null {
	if (!agentLogos.has(agent)) {
		let body: string | null = null;
		try {
			const svg = readFileSync(join(AGENT_LOGOS, `${agent}.svg`), "utf8");
			const fill = /fill="([^"]+)"/.exec(svg)?.[1] ?? "black";
			const rule = /fill-rule="([^"]+)"/.exec(svg)?.[1] ?? "nonzero";
			const paths = [...svg.matchAll(/<path d="([^"]+)"/g)].map((m) => `<path d="${m[1]}"/>`).join("");
			body = paths ? `<g fill="${fill}" fill-rule="${rule}">${paths}</g>` : null;
		} catch {
			body = null; // unknown agent; no badge
		}
		agentLogos.set(agent, body);
	}
	return agentLogos.get(agent) ?? null;
}

function rgb([r, g, b]: RGB): string {
	return `rgb(${r},${g},${b})`;
}

/** Light backgrounds (Grok's "your turn", approve) take dark text and a ringed badge. */
export function isLight([r, g, b]: RGB): boolean {
	return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.7;
}

const DARK_TEXT = "rgb(24,24,24)";

function escape(text: string): string {
	return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function placeLogo(logo: Logo, width: number, height: number): string {
	const size = logo.size * height;
	// valign/halign position the logo's box within the free space, like StreamController.
	const x = ((width - size) * ((logo.halign ?? 0) + 1)) / 2;
	const y = ((height - size) * (logo.valign + 1)) / 2;
	const opacity = logo.opacity ?? 1;
	return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)}) scale(${(size / 100).toFixed(4)})" opacity="${opacity}">${spark(rgb(logo.tint ?? CLAUDE_ORANGE))}</g>`;
}

/**
 * The agent's logo on a white disc in the bottom-right corner. The disc keeps
 * every logo legible, unaltered, on any key color.
 */
function placeBadge(agent: string, width: number, height: number, ringed: boolean): string {
	const body = agentLogo(agent);
	if (!body) return "";
	const size = 0.26 * height;
	const inset = 0.04 * height;
	const [cx, cy] = [width - inset - size / 2, height - inset - size / 2];
	const logoSize = size * 0.64;
	const at = `translate(${(cx - logoSize / 2).toFixed(1)},${(cy - logoSize / 2).toFixed(1)}) scale(${(logoSize / 24).toFixed(4)})`;
	const ring = ringed ? ` stroke="${DARK_TEXT}" stroke-width="${(size / 18).toFixed(1)}"` : "";
	return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(size / 2).toFixed(1)}" fill="white"${ring}/><g transform="${at}">${body}</g>`;
}

/**
 * Text with a dark outline: drawn twice, since paint-order isn't reliably supported.
 * Keys go through Qt's SVG Tiny renderer, which ignores positioned tspans and
 * dominant-baseline, so each line is its own <text> on an explicit baseline.
 */
function label(text: string, x: number, y: number, size: number, dark = false, lineHeight = 1.15): string {
	if (!text) return "";
	const lines = text.split("\n");
	// y is the vertical center of the block; 0.35em puts a line's middle there.
	const first = y - ((lines.length - 1) * size * lineHeight) / 2 + size * 0.35;
	const common = `font-family="${FONT}" font-size="${size}" font-weight="600" text-anchor="middle"`;
	const outline = dark
		? `fill="none" stroke="white" stroke-opacity="0.6" stroke-width="${(size / 7).toFixed(1)}" stroke-linejoin="round"`
		: `fill="none" stroke="black" stroke-opacity="0.8" stroke-width="${(size / 7).toFixed(1)}" stroke-linejoin="round"`;
	const fill = dark ? DARK_TEXT : "white";
	return lines
		.map((line, i) => {
			const at = `x="${x}" y="${(first + i * size * lineHeight).toFixed(1)}"`;
			return `<text ${at} ${common} ${outline}>${escape(line)}</text><text ${at} ${common} fill="${fill}">${escape(line)}</text>`;
		})
		.join("");
}

function svg(width: number, height: number, frame: Frame, scale: number): string {
	const background = frame.color ? rgb(frame.color) : "black";
	const center = (frame.centerSize ?? 14) * scale;
	const light = !!frame.color && isLight(frame.color);
	const body = [
		`<rect width="${width}" height="${height}" fill="${background}"/>`,
		frame.logo ? placeLogo(frame.logo, width, height) : "",
		frame.agent ? placeBadge(frame.agent, width, height, light) : "",
		label(frame.top, width / 2, height * 0.18, 12 * scale, light),
		label(frame.center, width / 2, height * 0.52, center, light),
		label(frame.bottom, width / 2, height * 0.86, 11 * scale, light),
	].join("");
	const doc = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${body}</svg>`;
	return `data:image/svg+xml;base64,${Buffer.from(doc).toString("base64")}`;
}

/** A key image. Label sizes are in StreamController points, scaled to the 144px key. */
export function keyImage(frame: Frame): string {
	return svg(144, 144, frame, 1.9);
}

/** A touch strip segment for the "canvas" item of layouts/canvas.json. */
export function stripImage(frame: Frame): string {
	return svg(200, 100, frame, 1.35);
}

const TRACK = "rgb(60,60,60)";
const DIM = "rgb(160,160,155)";

/**
 * The usage meter: two rows, one per window, with "5h 23%", a bar, and the time
 * until it resets (beside the label on a strip segment, under the bar on a key,
 * which is too narrow for both). Same layout as usage.py.
 */
function meterSvg(windows: UsageWindow[], width: number, height: number): string {
	const wide = width >= 1.5 * height;
	const pad = 8 * (width / (wide ? 200 : 120));
	const rowH = (height - pad) / 2;
	const textSize = rowH * (wide ? 0.36 : 0.3);
	const smallSize = textSize * (wide ? 0.8 : 0.75);
	const barH = rowH * (wide ? 0.2 : 0.16);
	const font = `font-family="${FONT}" font-weight="700"`;

	const rows = windows.map((w, i) => {
		const top = pad / 2 + i * rowH;
		const baseline = top + rowH * (wide ? 0.45 : 0.34);
		const barTop = top + rowH * (wide ? 0.62 : 0.46);
		const barW = width - 2 * pad;
		const filled = (Math.min(w.percent, 100) / 100) * barW;
		const reset = humanizeUntil(w.resetsAt);
		return [
			`<text x="${pad}" y="${baseline.toFixed(1)}" ${font} font-size="${textSize.toFixed(1)}" fill="white">${escape(`${w.label} ${Math.round(w.percent)}%`)}</text>`,
			`<rect x="${pad}" y="${barTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" rx="${(barH / 2).toFixed(1)}" fill="${TRACK}"/>`,
			filled >= 0.5
				? `<rect x="${pad}" y="${barTop.toFixed(1)}" width="${Math.max(filled, barH).toFixed(1)}" height="${barH.toFixed(1)}" rx="${(barH / 2).toFixed(1)}" fill="${rgb(usageColor(w.percent))}"/>`
				: "",
			!reset
				? ""
				: wide
					? `<text x="${width - pad}" y="${baseline.toFixed(1)}" ${font} font-size="${smallSize.toFixed(1)}" fill="${DIM}" text-anchor="end">${reset}</text>`
					: `<text x="${pad}" y="${(barTop + barH * 1.6 + smallSize * 0.8).toFixed(1)}" ${font} font-size="${smallSize.toFixed(1)}" fill="${DIM}">${reset}</text>`,
		].join("");
	});
	const doc = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="black"/>${rows.join("")}</svg>`;
	return `data:image/svg+xml;base64,${Buffer.from(doc).toString("base64")}`;
}

export function meterKeyImage(windows: UsageWindow[]): string {
	return meterSvg(windows, 144, 144);
}

export function meterStripImage(windows: UsageWindow[]): string {
	return meterSvg(windows, 200, 100);
}
