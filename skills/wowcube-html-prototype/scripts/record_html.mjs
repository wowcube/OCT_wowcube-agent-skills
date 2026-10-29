#!/usr/bin/env node
// Record a cube.js HTML prototype into an mp4, frame by frame on a virtual clock.
//
// The page runs on Playwright's fake clock: every video frame advances it by exactly 1000/fps ms and
// takes a screenshot, so the video is smooth whatever the machine's speed, and the same on every run.
// Frames go straight into ffmpeg (image2pipe), nothing is written to disk but the mp4.
//
// Usage:
//   node record_html.mjs <page.html> <out.mp4> [--seconds 45] [--fps 30] [--query "cinema&autoplay"]
//                        [--width 1280] [--height 720] [--scale 1.5] [--warmup 800] [--crf 18]
//                        [--stopWhen "window.__demoDone"] [--tail 1.5]
//
// Defaults give the team's video: the page's ?cinema layout at 1280 x 720 CSS px, scale 1.5 -> 1920 x 1080.
// --seconds is the limit; with --stopWhen the video ends --tail seconds after that expression turns true
// (the autopilot sets window.__demoDone at the end of its script).
// Needs: npm i playwright (Chromium), ffmpeg on PATH.

import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

// CommonJS resolution: finds a local, NODE_PATH or preinstalled playwright, which a bare ESM import does not
const { chromium } = createRequire(import.meta.url)('playwright');

const DEFAULTS = Object.freeze({
  seconds: 45,
  fps: 30,
  query: 'cinema&autoplay',
  width: 1280,
  height: 720,
  scale: 1.5,
  warmup: 800,          // ms of virtual time before the first frame: fonts, first layout, autoplay's own delay
  crf: 18,
  stopWhen: '',         // a JS expression: the video ends once it is true (plus the tail)
  tail: 1.5,            // seconds kept after stopWhen
});

const PAUSE_MARGIN_MS = 1000;   // pauseAt must lie ahead of the page's clock, which runs on while we ask it

function parseArgs(argv) {
  const pos = [];
  const opt = { ...DEFAULTS };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) { pos.push(a); continue; }
    const key = a.slice(2);
    if (!(key in DEFAULTS)) throw new Error(`unknown option ${a}`);
    const v = argv[++i];
    opt[key] = typeof DEFAULTS[key] === 'number' ? Number(v) : v;
  }
  if (pos.length !== 2) throw new Error('usage: record_html.mjs <page.html> <out.mp4> [options]');
  return { page: pos[0], out: pos[1], opt };
}

function startFfmpeg(out, fps, crf) {
  const args = ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(fps), '-i', '-',
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', String(crf), '-preset', 'medium', '-movflags', '+faststart', out];
  const ff = spawn('ffmpeg', args, { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((resolve, reject) => ff.on('close', (c) => (c === 0 ? resolve() : reject(new Error(`ffmpeg exit ${c}`)))));
  return { ff, done };
}

async function main() {
  const { page: file, out, opt } = parseArgs(process.argv.slice(2));
  const url = pathToFileURL(path.resolve(file)).href + (opt.query ? `?${opt.query}` : '');
  const frames = Math.round(opt.seconds * opt.fps);
  const stepMs = 1000 / opt.fps;

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: opt.width, height: opt.height }, deviceScaleFactor: opt.scale });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.clock.install();                         // Date, timers, rAF and performance.now on the fake clock
  await page.goto(url, { waitUntil: 'load' });
  // An installed clock still flows with real time (and a screenshot takes ~0.2 s): stop it, so only
  // runFor moves the page's time.
  await page.clock.pauseAt(await page.evaluate(() => Date.now()) + PAUSE_MARGIN_MS);
  await page.addStyleTag({ content: '*, *::before, *::after { transition-duration: 0s !important; animation-duration: 0s !important; }' });
  await page.clock.runFor(opt.warmup);

  const { ff, done } = startFfmpeg(out, opt.fps, opt.crf);
  const tailFrames = Math.round(opt.tail * opt.fps);
  let last = frames;
  let written = 0;
  for (let i = 0; i < last; i++) {
    const png = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once('drain', r));
    written++;
    await page.clock.runFor(stepMs);
    if (opt.stopWhen && last === frames && await page.evaluate((e) => !!(0, eval)(e), opt.stopWhen)) {
      last = Math.min(frames, i + 1 + tailFrames);
    }
    if (i % (opt.fps * 5) === 0) process.stdout.write(`\r${(i / opt.fps).toFixed(0)} / ${opt.seconds} s`);
  }
  ff.stdin.end();
  await done;
  await browser.close();
  process.stdout.write(`\r${out}: ${written} frames, ${(written / opt.fps).toFixed(1)} s at ${opt.fps} fps\n`);
  if (opt.stopWhen && last === frames) console.error(`stopWhen never turned true in ${opt.seconds} s`);
  if (errors.length) {
    console.error(`page errors (${errors.length}):\n  ` + errors.slice(0, 10).join('\n  '));
    process.exitCode = 2;
  }
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });
