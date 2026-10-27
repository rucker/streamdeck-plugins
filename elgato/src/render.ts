/**
 * Draws keys (144×144) and touch strip segments (200×100) as SVG, mirroring
 * how the StreamController plugin lays out its labels and logo.
 */

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const CLAUDE_ORANGE: RGB = [217, 119, 87];
export const CLAUDE_CREAM: RGB = [250, 249, 245];

export type RGB = [number, number, number];

/**
 * If you'd rather use the official Claude logo, put a PNG here; it's used
 * instead of the drawn spark. It deliberately lives outside the repo so the
 * trademark isn't redistributed. (It isn't recolored on orange/red keys.)
 */
const USER_LOGO_PATH = join(homedir(), ".local", "share", "claude-deck", "logo.png");

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

/** Small mark in the bottom-right corner of session keys, beside the age. */
export function logoCorner(onColor: boolean): Logo {
	return { size: 0.24, valign: 0.92, halign: 0.92, tint: onColor ? CLAUDE_CREAM : undefined };
}

export type Frame = {
	top: string;
	center: string;
	bottom: string;
	color: RGB | null; // null = black (empty)
	centerSize?: number; // in StreamController's key-label points (14 = normal)
	logo?: Logo;
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

let userLogo: string | null | undefined;

function userLogoDataUrl(): string | null {
	if (userLogo === undefined) {
		try {
			userLogo = existsSync(USER_LOGO_PATH)
				? `data:image/png;base64,${readFileSync(USER_LOGO_PATH).toString("base64")}`
				: null;
		} catch {
			userLogo = null; // unreadable; fall back to the drawn spark
		}
	}
	return userLogo;
}

function rgb([r, g, b]: RGB): string {
	return `rgb(${r},${g},${b})`;
}

function escape(text: string): string {
	return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function placeLogo(logo: Logo, width: number, height: number): string {
	const size = logo.size * height;
	// valign/halign position the logo's box within the free space, like StreamController.
	const x = ((width - size) * ((logo.halign ?? 0) + 1)) / 2;
	const y = ((height - size) * (logo.valign + 1)) / 2;
	const opacity = logo.opacity ?? 1;
	const user = userLogoDataUrl();
	const body = user
		? `<image href="${user}" width="100" height="100" preserveAspectRatio="xMidYMid meet"/>`
		: spark(rgb(logo.tint ?? CLAUDE_ORANGE));
	return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)}) scale(${(size / 100).toFixed(4)})" opacity="${opacity}">${body}</g>`;
}

/** Text with a dark outline: drawn twice, since paint-order isn't reliably supported. */
function label(text: string, x: number, y: number, size: number, lineHeight = 1.15): string {
	if (!text) return "";
	const lines = text.split("\n");
	// y is the vertical center of the block.
	const first = y - ((lines.length - 1) * size * lineHeight) / 2;
	const tspans = lines
		.map((line, i) => `<tspan x="${x}" y="${(first + i * size * lineHeight).toFixed(1)}">${escape(line)}</tspan>`)
		.join("");
	const common = `font-family="${FONT}" font-size="${size}" font-weight="600" text-anchor="middle" dominant-baseline="central"`;
	return (
		`<text ${common} fill="none" stroke="rgba(0,0,0,0.8)" stroke-width="${(size / 7).toFixed(1)}" stroke-linejoin="round">${tspans}</text>` +
		`<text ${common} fill="white">${tspans}</text>`
	);
}

function svg(width: number, height: number, frame: Frame, scale: number): string {
	const background = frame.color ? rgb(frame.color) : "black";
	const center = (frame.centerSize ?? 14) * scale;
	const body = [
		`<rect width="${width}" height="${height}" fill="${background}"/>`,
		frame.logo ? placeLogo(frame.logo, width, height) : "",
		label(frame.top, width / 2, height * 0.18, 12 * scale),
		label(frame.center, width / 2, height * 0.52, center),
		label(frame.bottom, width / 2, height * 0.86, 11 * scale),
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
