/*
 * WowCube 2x2x2 demo engine.
 *
 * Model: 8 modules (corners), 3 screens each = 24 screens. A twist rotates one half of the
 * cube by 90 degrees; the three screens of a module always move together.
 * Views: CSS-3D cube (drag to orbit/tilt, click = "pat") and a cross-shaped 2D net.
 *
 * Two kinds of apps plug in via CubeDemo.mount({...}):
 *   - puzzle (default): content lives on modules and moves with twists; the game describes
 *     content, optional HUD screens and goal evaluation;
 *   - interactive: every screen is drawn by position (slot); twists are input events
 *     (onTwist), an optional tick() drives animation, gravity comes from the 3D view tilt.
 */
(function (global) {
  'use strict';

  /* =============================== Config =============================== */

  const CONFIG = Object.freeze({
    SCREEN_RES: 240,
    SCREENS: 24,
    MODULES: 8,
    SCREENS_PER_FACE: 4,
    VIEW: Object.freeze({
      UNIT_MAX_PX: 118,
      UNIT_MIN_PX: 62,
      UNIT_WIDTH_DIV: 3.9,
      SCENE_HEIGHT_K: 3.55,
      TARGET_UNIT_PX: 38,
      DEFAULT_PITCH: -27,
      DEFAULT_YAW: -36,
      PITCH_LIMIT: 85,
      DRAG_DEG_PER_PX: 0.45,
      KEY_TILT_DEG: 6,
      CLICK_SLOP_PX: 5,
      CAP_EPS: 0.004,
      MATRIX_DIGITS: 5,
    }),
    ANIM: Object.freeze({
      TWIST_MS: 260,
      FAST_MS: 110,
      WIGGLE_MS: 240,                 // half twist: the layer nudges and springs back
      WIGGLE_FRAC: 0.2,               // peak angle of a half twist, in quarter turns
      FLASH_MS: 650,
      TICK_RENDER_MS: 33,
      STATUS_MS: 250,
      MAX_DT_S: 0.05,
    }),
    RANDOM_SCRAMBLE_LEN: 14,
    CANVAS_RES: 160,                  // backing pixels of a canvas screen (drawn in 240-unit coordinates)
    AUDIO: Object.freeze({
      GAIN: 0.22,
      ATTACK_S: 0.01,
      DEFAULT_MS: 450,
      WAVE: 'triangle',
    }),
    FONT: "'Segoe UI', system-ui, -apple-system, Roboto, Arial, sans-serif",
    EMOJI_FONT: "'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif",
    EPS: 1e-6,
  });

  const MODE = Object.freeze({ PUZZLE: 'puzzle', INTERACTIVE: 'interactive' });

  const VIEW_PRESETS = Object.freeze([
    { label: 'Front', pitch: -27, yaw: -36 },
    { label: 'Back', pitch: -27, yaw: 144 },
    { label: 'Bottom', pitch: 30, yaw: -36 },
    { label: 'Top', pitch: -80, yaw: 0 },
  ]);

  const AXIS = Object.freeze({ X: 0, Y: 1, Z: 2 });
  const EDGE = Object.freeze({ UP: 0, RIGHT: 1, DOWN: 2, LEFT: 3 });
  const EDGE_COUNT = 4;
  const ROW = Object.freeze({ TOP: 0, BOTTOM: 1 });

  /* Face frames: n = outward normal, r/u = right/up when looking at the face from outside.
     Net layout (cross):      U
                           L  F  R  B
                              D                                                          */
  const FACE_IDS = Object.freeze(['U', 'L', 'F', 'R', 'B', 'D']);
  const FACES = Object.freeze({
    U: { n: [0, 1, 0], r: [1, 0, 0], u: [0, 0, -1], name: 'Up' },
    L: { n: [-1, 0, 0], r: [0, 0, 1], u: [0, 1, 0], name: 'Left' },
    F: { n: [0, 0, 1], r: [1, 0, 0], u: [0, 1, 0], name: 'Front' },
    R: { n: [1, 0, 0], r: [0, 0, -1], u: [0, 1, 0], name: 'Right' },
    B: { n: [0, 0, -1], r: [-1, 0, 0], u: [0, 1, 0], name: 'Back' },
    D: { n: [0, -1, 0], r: [1, 0, 0], u: [0, 0, 1], name: 'Down' },
  });
  const NET_POS = Object.freeze({ U: [2, 0], L: [0, 2], F: [2, 2], R: [4, 2], B: [6, 2], D: [2, 4] });
  const SIDE_RING = Object.freeze(['F', 'R', 'B', 'L']);

  /* Standard notation; quarter = rotation sign around +axis (right-hand rule). */
  const MOVES = Object.freeze({
    U: { axis: AXIS.Y, layer: 1, quarter: -1, name: 'Up' },
    D: { axis: AXIS.Y, layer: -1, quarter: 1, name: 'Down' },
    R: { axis: AXIS.X, layer: 1, quarter: -1, name: 'Right' },
    L: { axis: AXIS.X, layer: -1, quarter: 1, name: 'Left' },
    F: { axis: AXIS.Z, layer: 1, quarter: -1, name: 'Front' },
    B: { axis: AXIS.Z, layer: -1, quarter: 1, name: 'Back' },
  });
  const MOVE_IDS = Object.freeze(['U', 'D', 'R', 'L', 'F', 'B']);
  const KEY_TO_MOVE = Object.freeze({ KeyU: 'U', KeyD: 'D', KeyR: 'R', KeyL: 'L', KeyF: 'F', KeyB: 'B' });
  const KEY_TO_TILT = Object.freeze({ ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] });

  /* Face orders inside one face (slot offsets). */
  const FACE_ORDER = Object.freeze({
    reading: [0, 1, 2, 3],   // TL TR BL BR
    cw: [0, 1, 3, 2],        // TL TR BR BL
  });

  /* ============================== Vectors =============================== */

  const V = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    scale: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
    neg: (a) => [-a[0], -a[1], -a[2]],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
    len: (a) => Math.hypot(a[0], a[1], a[2]),
    eq: (a, b) => Math.abs(a[0] - b[0]) < CONFIG.EPS && Math.abs(a[1] - b[1]) < CONFIG.EPS && Math.abs(a[2] - b[2]) < CONFIG.EPS,
    unit: (axis) => [axis === AXIS.X ? 1 : 0, axis === AXIS.Y ? 1 : 0, axis === AXIS.Z ? 1 : 0],
    /* Exact quarter turn around an axis, q = +1 / -1. */
    rotQ(v, axis, q) {
      const [x, y, z] = v;
      if (axis === AXIS.X) return q > 0 ? [x, -z, y] : [x, z, -y];
      if (axis === AXIS.Y) return q > 0 ? [z, y, -x] : [-z, y, x];
      return q > 0 ? [-y, x, z] : [y, -x, z];
    },
    /* Arbitrary rotation (radians) used only for animation. */
    rotA(v, axis, a) {
      const c = Math.cos(a), s = Math.sin(a), [x, y, z] = v;
      if (axis === AXIS.X) return [x, y * c - z * s, y * s + z * c];
      if (axis === AXIS.Y) return [x * c + z * s, y, -x * s + z * c];
      return [x * c - y * s, x * s + y * c, z];
    },
  };

  /* ============================ Slot helpers ============================ */

  const slotIndex = (face, row, col) => FACE_IDS.indexOf(face) * CONFIG.SCREENS_PER_FACE + row * 2 + col;
  const slotInfo = (slot) => ({ face: FACE_IDS[slot >> 2], row: (slot >> 1) & 1, col: slot & 1 });

  function slotCenter(slot) {
    const { face, row, col } = slotInfo(slot);
    const f = FACES[face];
    return V.add(V.add(f.n, V.scale(f.r, col ? 0.5 : -0.5)), V.scale(f.u, row ? -0.5 : 0.5));
  }
  const faceOfNormal = (n) => FACE_IDS.find((id) => V.eq(FACES[id].n, n));
  function slotOfVec(pos, n) {
    const face = faceOfNormal(n);
    const f = FACES[face];
    return slotIndex(face, V.dot(pos, f.u) > 0 ? ROW.TOP : ROW.BOTTOM, V.dot(pos, f.r) > 0 ? 1 : 0);
  }
  /* Quarter turns (clockwise, seen from outside) from the face "up" to vector v. -1 if not in plane. */
  function quarterInFace(face, v) {
    const f = FACES[face];
    const dirs = [f.u, f.r, V.neg(f.u), V.neg(f.r)];
    return dirs.findIndex((d) => V.eq(d, v));
  }
  /* Slots of the 8-screen belt around the side faces, row = 0 (top) or 1 (bottom). */
  const ringSlots = (row) => SIDE_RING.flatMap((face) => [slotIndex(face, row, 0), slotIndex(face, row, 1)]);
  const faceSlots = (face, order = 'reading') => FACE_ORDER[order].map((o) => FACE_IDS.indexOf(face) * CONFIG.SCREENS_PER_FACE + o);

  /* ============================ Move tokens ============================= */

  function parseMoves(str) {
    const out = [];
    for (const raw of String(str || '').trim().split(/\s+/)) {
      if (!raw) continue;
      const m = /^([UDLRFB])(2|'|’)?$/.exec(raw);
      if (!m) throw new Error('Bad move token: ' + raw);
      if (m[2] === '2') out.push(m[1], m[1]);
      else out.push(m[1] + (m[2] ? "'" : ''));
    }
    return out;
  }
  const invertToken = (t) => (t.endsWith("'") ? t.slice(0, -1) : t + "'");
  function tokenInfo(token) {
    const move = MOVES[token[0]];
    return { move, q: token.endsWith("'") ? -move.quarter : move.quarter };
  }
  /* +1 for a clockwise twist (looking at that layer's face), -1 for counter-clockwise. */
  const twistSign = (token) => (token.endsWith("'") ? -1 : 1);

  /* ================================ Model =============================== */

  class CubeModel {
    constructor(contents) {
      this.stickers = [];
      const perModule = new Array(CONFIG.MODULES).fill(0);
      for (let slot = 0; slot < CONFIG.SCREENS; slot++) {
        const f = FACES[slotInfo(slot).face];
        const pos = slotCenter(slot);
        const cubie = V.sub(pos, V.scale(f.n, 0.5));
        const module = (cubie[0] > 0 ? 1 : 0) | (cubie[1] > 0 ? 2 : 0) | (cubie[2] > 0 ? 4 : 0);
        this.stickers.push({
          id: slot,
          homeSlot: slot,
          slot,
          module,
          screen: perModule[module]++,
          content: contents ? (contents[slot] ?? null) : null,
          pos,
          n: f.n.slice(),
          up: f.u.slice(),
        });
      }
      this.history = [];
      this.reindex();
    }

    reindex() {
      this.bySlot = new Array(CONFIG.SCREENS);
      for (const s of this.stickers) {
        s.slot = slotOfVec(s.pos, s.n);
        this.bySlot[s.slot] = s;
      }
    }

    at(slot) { return this.bySlot[slot]; }

    layerOf(move) {
      return this.stickers.filter((s) => {
        const cubie = V.sub(s.pos, V.scale(s.n, 0.5));
        return Math.sign(cubie[move.axis]) === move.layer;
      });
    }

    turn(token) {
      const { move, q } = tokenInfo(token);
      for (const s of this.layerOf(move)) {
        s.pos = V.rotQ(s.pos, move.axis, q);
        s.n = V.rotQ(s.n, move.axis, q);
        s.up = V.rotQ(s.up, move.axis, q);
      }
      this.reindex();
    }

    apply(token, record = true) {
      this.turn(token);
      if (!record) return;
      const last = this.history[this.history.length - 1];
      if (last && last === invertToken(token)) this.history.pop();
      else this.history.push(token);
    }

    isHome() {
      return this.stickers.every((s) => s.slot === s.homeSlot && V.eq(s.up, FACES[slotInfo(s.homeSlot).face].u));
    }

    faceOf(s) { return slotInfo(s.slot).face; }

    /* Physical rotation of the sticker content: 0..3 clockwise quarter turns vs the face frame. */
    rotOf(s) { return quarterInFace(this.faceOf(s), s.up); }

    /* Physical direction of a content edge (EDGE.*) as defined in the solved state. */
    edgeDir(s, edge) {
      const right = V.cross(s.up, s.n);
      return [s.up, right, V.neg(s.up), V.neg(right)][edge];
    }

    edgeAt(s, dir) {
      for (let e = 0; e < EDGE_COUNT; e++) if (V.eq(this.edgeDir(s, e), dir)) return e;
      return -1;
    }

    /* Screen adjacent across the edge in direction dir (unit vector in the screen plane).
       Returns the neighbour, the direction pointing back from it, and the travel heading on it. */
    neighbor(s, dir) {
      const wraps = V.dot(s.pos, dir) > 0;
      const pos = wraps ? V.sub(V.add(s.pos, V.scale(dir, 0.5)), V.scale(s.n, 0.5)) : V.add(s.pos, dir);
      const n = wraps ? dir : s.n;
      return {
        sticker: this.bySlot[slotOfVec(pos, n)],
        backDir: wraps ? s.n.slice() : V.neg(dir),
        heading: wraps ? V.neg(s.n) : dir.slice(),
      };
    }

    faceStickers(face, order = 'reading') { return faceSlots(face, order).map((slot) => this.bySlot[slot]); }
    ring(row) { return ringSlots(row).map((slot) => this.bySlot[slot]); }

    /* Generic edge-connector matching for pipe/bond style puzzles.
       stubsOf(sticker) -> array[4] of connector values in content edges (0 = none). */
    matchConnectors(stubsOf) {
      const result = new Map();
      let total = 0, matched = 0;
      for (const s of this.stickers) {
        const stubs = stubsOf(s);
        if (!stubs) continue;
        const ok = [false, false, false, false];
        const links = [null, null, null, null];
        for (let e = 0; e < EDGE_COUNT; e++) {
          if (!stubs[e]) continue;
          total++;
          const nb = this.neighbor(s, this.edgeDir(s, e));
          const otherStubs = stubsOf(nb.sticker);
          const e2 = this.edgeAt(nb.sticker, nb.backDir);
          if (otherStubs && otherStubs[e2] === stubs[e]) { ok[e] = true; links[e] = nb.sticker.id; matched++; }
        }
        result.set(s.id, { ok, links, stubs });
      }
      return { map: result, total, matched };
    }
  }

  /* ============================== SVG kit =============================== */

  const SVG = {
    esc: (str) => String(str).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
    wrap: (inner) => `<svg class="cv-svg" viewBox="0 0 ${CONFIG.SCREEN_RES} ${CONFIG.SCREEN_RES}" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`,
    bg: (fill) => `<rect width="240" height="240" fill="${fill}"/>`,
    text(x, y, str, o = {}) {
      return `<text x="${x}" y="${y}" font-size="${o.size || 32}" fill="${o.fill || '#fff'}" font-weight="${o.weight || 600}"`
        + ` text-anchor="${o.anchor || 'middle'}" dominant-baseline="central" font-family="${o.font || CONFIG.FONT}"`
        + `${o.opacity != null ? ` opacity="${o.opacity}"` : ''}${o.extra || ''}>${SVG.esc(str)}</text>`;
    },
    emoji: (x, y, size, ch) => SVG.text(x, y, ch, { size, font: CONFIG.EMOJI_FONT, weight: 400 }),
    rot: (k, inner, cx = 120, cy = 120) => (k ? `<g transform="rotate(${k * 90} ${cx} ${cy})">${inner}</g>` : inner),
    /* Show the (row, col) quarter of a 480x480 face picture on one 240x240 screen. */
    facePart: (row, col, inner) => `<g transform="translate(${-col * 240} ${-row * 240})">${inner}</g>`,
    frame: (color, w = 10, r = 18) => `<rect x="${w / 2}" y="${w / 2}" width="${240 - w}" height="${240 - w}" rx="${r}" fill="none" stroke="${color}" stroke-width="${w}"/>`,
    blank: () => SVG.bg('#0b0d12')
      + '<g stroke="#1a1e27" stroke-width="2"><path d="M60 0V240M120 0V240M180 0V240M0 60H240M0 120H240M0 180H240"/></g>',
    /* Small corner badge, e.g. to show what a HUD screen currently hides. */
    badge(str, fill = '#ffb547', ink = '#1b1300') {
      const w = Math.max(44, 16 + String(str).length * 13);
      return `<rect x="8" y="8" width="${w}" height="30" rx="8" fill="${fill}" opacity=".92"/>`
        + SVG.text(8 + w / 2, 23, str, { size: 18, fill: ink, weight: 700 });
    },
    /* Unit offsets for EDGE.* in screen coordinates (y down). */
    EDGE_VEC: [[0, -1], [1, 0], [0, 1], [-1, 0]],
  };

  /* ============================= Canvas kit ============================= */
  /* Canvas screens are drawn in the same 240x240 coordinate space as SVG screens. */

  const CV = {
    text(g, x, y, str, o = {}) {
      g.save();
      g.font = `${o.weight || 600} ${o.size || 32}px ${o.font || CONFIG.FONT}`;
      g.fillStyle = o.fill || '#fff';
      g.globalAlpha = o.opacity != null ? o.opacity : 1;
      g.textAlign = o.align || 'center';
      g.textBaseline = 'middle';
      g.fillText(String(str), x, y);
      g.restore();
    },
    /* Run draw(g) in a 480x480 face picture space and show the (row, col) quarter of it. */
    facePart(g, row, col, draw) {
      g.save();
      g.beginPath();
      g.rect(0, 0, 240, 240);
      g.clip();
      g.translate(-col * 240, -row * 240);
      draw(g);
      g.restore();
    },
    /* Line chart inside a rectangle: series = [{ values, color, max, label }]. */
    chart(g, x, y, w, h, series, o = {}) {
      g.save();
      g.fillStyle = o.bg || '#0b0f16';
      g.fillRect(x, y, w, h);
      g.strokeStyle = 'rgba(255,255,255,.08)';
      g.lineWidth = 2;
      for (let k = 1; k < 4; k++) {
        g.beginPath();
        g.moveTo(x, y + (h * k) / 4);
        g.lineTo(x + w, y + (h * k) / 4);
        g.stroke();
      }
      for (const sr of series) {
        const v = sr.values;
        if (v.length < 2) continue;
        const max = sr.max || Math.max(1, ...v);
        g.strokeStyle = sr.color;
        g.lineWidth = o.line || 5;
        g.beginPath();
        v.forEach((val, i) => {
          const px = x + (i / (v.length - 1)) * w;
          const py = y + h - (Math.min(val, max) / max) * h;
          if (i) g.lineTo(px, py); else g.moveTo(px, py);
        });
        g.stroke();
      }
      g.restore();
    },
  };

  /* Uniform grid over the whole cube surface: n x n cells per screen, 2n x 2n per face.
     Neighbours wrap across cube edges, so fields (waves, diffusion, grass) flow around the cube. */
  class SurfaceGrid {
    constructor(nPerScreen) {
      const n = nPerScreen, N = 2 * n;
      this.n = n;
      this.N = N;
      this.count = FACE_IDS.length * N * N;
      this.h = 2 / N;
      this.faceOf = new Uint8Array(this.count);
      this.pos = new Float32Array(this.count * 3);
      this.nb = new Int32Array(this.count * EDGE_COUNT);
      for (let fi = 0; fi < FACE_IDS.length; fi++) {
        for (let j = 0; j < N; j++) {
          for (let i = 0; i < N; i++) {
            const c = this.index(fi, i, j);
            const p = this.center(fi, i, j);
            this.faceOf[c] = fi;
            this.pos.set(p, c * 3);
          }
        }
      }
      for (let c = 0; c < this.count; c++) {
        for (let e = 0; e < EDGE_COUNT; e++) this.nb[c * EDGE_COUNT + e] = this.step(c, e);
      }
      this.off = document.createElement('canvas');
      this.off.width = this.off.height = n;
      this.offG = this.off.getContext('2d');
      this.img = this.offG.createImageData(n, n);
    }

    index(fi, i, j) { return (fi * this.N + j) * this.N + i; }

    center(fi, i, j) {
      const f = FACES[FACE_IDS[fi]];
      const a = -1 + (i + 0.5) * this.h, b = 1 - (j + 0.5) * this.h;
      return V.add(V.add(f.n, V.scale(f.r, a)), V.scale(f.u, b));
    }

    cellAt(pos, n) {
      const fi = FACE_IDS.indexOf(faceOfNormal(n));
      const f = FACES[FACE_IDS[fi]];
      const clampI = (k) => Math.max(0, Math.min(this.N - 1, k));
      const i = clampI(Math.floor((V.dot(pos, f.r) + 1) / this.h));
      const j = clampI(Math.floor((1 - V.dot(pos, f.u)) / this.h));
      return this.index(fi, i, j);
    }

    /* Neighbour in face direction e (EDGE.*), crossing to the next face at an edge. */
    step(c, e) {
      const f = FACES[FACE_IDS[this.faceOf[c]]];
      const d = [f.u, f.r, V.neg(f.u), V.neg(f.r)][e];
      const p = [this.pos[c * 3], this.pos[c * 3 + 1], this.pos[c * 3 + 2]];
      const cand = V.add(p, V.scale(d, this.h));
      if (V.dot(cand, d) < 1) return this.cellAt(cand, f.n);
      return this.cellAt(V.sub(V.add(p, V.scale(d, this.h / 2)), V.scale(f.n, this.h / 2)), d);
    }

    neighbor(c, e) { return this.nb[c * EDGE_COUNT + e]; }

    /* Cells shown on one screen, row-major, matching screen pixels. */
    screenCell(slot, x, y) {
      const { face, row, col } = slotInfo(slot);
      return this.index(FACE_IDS.indexOf(face), col * this.n + x, row * this.n + y);
    }

    /* Centre of a cell in the 240-unit coordinates of its screen. */
    cellXY(c) {
      const k = c % (this.N * this.N);
      const i = k % this.N, j = Math.floor(k / this.N);
      const s = CONFIG.SCREEN_RES / this.n;
      return { x: ((i % this.n) + 0.5) * s, y: ((j % this.n) + 0.5) * s, col: Math.floor(i / this.n), row: Math.floor(j / this.n) };
    }

    slotOfCell(c) {
      const fi = this.faceOf[c];
      const xy = this.cellXY(c);
      return slotIndex(FACE_IDS[fi], xy.row, xy.col);
    }

    /* Paint one screen: rgbOf(cell) -> [r, g, b]. smooth = bilinear upscaling. */
    paint(g, slot, rgbOf, smooth = true) {
      const d = this.img.data;
      for (let y = 0; y < this.n; y++) {
        for (let x = 0; x < this.n; x++) {
          const rgb = rgbOf(this.screenCell(slot, x, y));
          const o = (y * this.n + x) * 4;
          d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = 255;
        }
      }
      this.offG.putImageData(this.img, 0, 0);
      g.save();
      g.imageSmoothingEnabled = smooth;
      g.drawImage(this.off, 0, 0, CONFIG.SCREEN_RES, CONFIG.SCREEN_RES);
      g.restore();
    }
  }

  /* Spheres inside the cube (a glass box, coordinates -1..1) seen through one screen. */
  const BOX_VIEW = Object.freeze({ PX_PER_UNIT: 240, PERSPECTIVE_K: 0.22, DEPTH_FADE: 0.3 });
  function paintParticles(g, face, row, col, items) {
    const f = FACES[face];
    const vis = [];
    for (const it of items) {
      const depth = 1 - V.dot(it.p, f.n);
      const x = (V.dot(it.p, f.r) + 1 - col) * BOX_VIEW.PX_PER_UNIT;
      const y = (1 - row - V.dot(it.p, f.u)) * BOX_VIEW.PX_PER_UNIT;
      const rad = (it.r * BOX_VIEW.PX_PER_UNIT) / (1 + depth * BOX_VIEW.PERSPECTIVE_K);
      if (x + rad < 0 || x - rad > 240 || y + rad < 0 || y - rad > 240) continue;
      vis.push({ it, depth, x, y, rad });
    }
    vis.sort((a, b) => b.depth - a.depth);
    for (const v of vis) {
      g.globalAlpha = Math.max(0.25, 1 - v.depth * BOX_VIEW.DEPTH_FADE);
      g.fillStyle = v.it.color;
      g.beginPath();
      g.arc(v.x, v.y, v.rad, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = 'rgba(255,255,255,.45)';
      g.beginPath();
      g.arc(v.x - v.rad * 0.35, v.y - v.rad * 0.35, v.rad * 0.3, 0, Math.PI * 2);
      g.fill();
    }
    g.globalAlpha = 1;
  }

  /* =============================== Audio ================================ */

  const Sound = {
    ctx: null,
    ensure() {
      if (!this.ctx) {
        const Ctx = global.AudioContext || global.webkitAudioContext;
        if (!Ctx) return null;
        this.ctx = new Ctx();
      }
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return this.ctx;
    },
    tone(freq, ms = CONFIG.AUDIO.DEFAULT_MS, delayMs = 0, wave = CONFIG.AUDIO.WAVE) {
      const ctx = this.ensure();
      if (!ctx) return;
      const t0 = ctx.currentTime + delayMs / 1000;
      const t1 = t0 + ms / 1000;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = wave;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, t0);
      gain.gain.linearRampToValueAtTime(CONFIG.AUDIO.GAIN, t0 + CONFIG.AUDIO.ATTACK_S);
      gain.gain.exponentialRampToValueAtTime(0.0001, t1);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t1 + 0.02);
    },
  };

  /* ============================ DOM helpers ============================= */

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const DEG = Math.PI / 180;
  const num = (x) => {
    const v = +x.toFixed(CONFIG.VIEW.MATRIX_DIGITS);
    return Object.is(v, -0) ? 0 : v;
  };
  const toCss = (v) => [v[0], -v[1], v[2]];

  function cssMatrix(fr, unit) {
    const X = toCss(fr.R), Y = toCss(V.neg(fr.U)), Z = toCss(fr.N), T = toCss(V.scale(fr.C, unit));
    return `matrix3d(${[...X, 0, ...Y, 0, ...Z, 0, ...T, 1].map(num).join(',')})`;
  }
  function rotFrame(fr, axis, a) {
    return { R: V.rotA(fr.R, axis, a), U: V.rotA(fr.U, axis, a), N: V.rotA(fr.N, axis, a), C: V.rotA(fr.C, axis, a) };
  }

  /* 3x3 rotation matrices (rows) in model coordinates (y up), used by the free-orientation view. */
  const M3 = {
    mul: (A, B) => A.map((row) => [0, 1, 2].map((j) => row[0] * B[0][j] + row[1] * B[1][j] + row[2] * B[2][j])),
    apply: (A, v) => A.map((row) => row[0] * v[0] + row[1] * v[1] + row[2] * v[2]),
    transpose: (A) => [0, 1, 2].map((i) => [A[0][i], A[1][i], A[2][i]]),
    rot(axis, a) {
      const c = Math.cos(a), s = Math.sin(a);
      if (axis === AXIS.X) return [[1, 0, 0], [0, c, -s], [0, s, c]];
      if (axis === AXIS.Y) return [[c, 0, s], [0, 1, 0], [-s, 0, c]];
      return [[c, -s, 0], [s, c, 0], [0, 0, 1]];
    },
    /* Same orientation as the CSS transform rotateZ(roll) rotateX(pitch) rotateY(yaw) (CSS y points down). */
    euler(pitch, yaw, roll = 0) {
      return M3.mul(M3.mul(M3.rot(AXIS.Z, -roll * DEG), M3.rot(AXIS.X, -pitch * DEG)), M3.rot(AXIS.Y, yaw * DEG));
    },
    /* CSS matrix3d of a model-space rotation (flip y on both sides, column-major). */
    css(A) {
      const sg = [1, -1, 1];
      const c = (i, j) => num(sg[i] * sg[j] * A[i][j]);
      return `matrix3d(${c(0, 0)},${c(1, 0)},${c(2, 0)},0,${c(0, 1)},${c(1, 1)},${c(2, 1)},0,${c(0, 2)},${c(1, 2)},${c(2, 2)},0,0,0,0,1)`;
    },
  };

  /* Put a drawing on a screen element: SVG markup or a canvas painter. */
  function applyDraw(e, d) {
    if (d.paint) {
      if (!e._canvas) {
        e._scr.innerHTML = '';
        const c = document.createElement('canvas');
        c.width = c.height = CONFIG.CANVAS_RES;
        c.className = 'cv-svg';
        e._scr.appendChild(c);
        e._canvas = c;
        e._g = c.getContext('2d');
        e._svg = null;
      }
      const k = CONFIG.CANVAS_RES / CONFIG.SCREEN_RES;
      e._g.setTransform(k, 0, 0, k, 0, 0);
      e._g.clearRect(0, 0, CONFIG.SCREEN_RES, CONFIG.SCREEN_RES);
      d.paint(e._g);
      return;
    }
    if (d.svg !== e._svg) {
      e._canvas = null;
      e._scr.innerHTML = SVG.wrap(d.svg);
      e._svg = d.svg;
    }
  }

  /* ============================== 3D view =============================== */

  class View3D {
    constructor(host, opts = {}) {
      this.host = host;
      this.opts = opts;
      this.pitch = opts.pitch ?? CONFIG.VIEW.DEFAULT_PITCH;
      this.yaw = opts.yaw ?? CONFIG.VIEW.DEFAULT_YAW;
      /* Orientation mode: the cube has a full 3D orientation R (model -> view), the camera looks down by elev degrees. */
      this.elev = opts.elev || 0;
      this.R = opts.orient ? M3.euler(this.pitch, this.yaw) : null;
      this.unit = opts.unit || CONFIG.VIEW.UNIT_MAX_PX;
      this.scene = el('div', 'cv-scene' + (opts.mini ? ' is-mini' : ''));
      this.cube = el('div', 'cv-cube');
      this.scene.appendChild(this.cube);
      host.appendChild(this.scene);
      this.caps = [el('div', 'cv-cap'), el('div', 'cv-cap')];
      this.caps.forEach((c) => this.cube.appendChild(c));
      this.els = [];
      this.bindPointer();
      this.applyView();
    }

    setModel(model) {
      this.model = model;
      this.els.forEach((e) => e.remove());
      this.els = model.stickers.map((s) => {
        const e = el('div', 'cv-st', '<div class="cv-scr"></div><div class="cv-lbl"></div>');
        e.dataset.sid = s.id;
        e._scr = e.firstChild;
        e._lbl = e.lastChild;
        e._svg = '';
        this.cube.appendChild(e);
        return e;
      });
      this.resize();
    }

    resize() {
      const VC = CONFIG.VIEW;
      if (!this.opts.mini) {
        const w = this.host.clientWidth || 480;
        this.unit = clamp(Math.round(w / VC.UNIT_WIDTH_DIV), VC.UNIT_MIN_PX, VC.UNIT_MAX_PX);
        this.scene.style.height = Math.round(this.unit * VC.SCENE_HEIGHT_K) + 'px';
      }
      const u = this.unit;
      const size = (e, k) => Object.assign(e.style, { width: k * u + 'px', height: k * u + 'px', left: -k * u / 2 + 'px', top: -k * u / 2 + 'px' });
      this.els.forEach((e) => size(e, 1));
      this.caps.forEach((c) => size(c, 2));
      this.layout();
    }

    applyView() {
      this.cube.style.transform = this.R
        ? `rotateX(${-this.elev}deg) ${M3.css(this.R)}`
        : `rotateX(${this.pitch}deg) rotateY(${this.yaw}deg)`;
      if (this.opts.onView) this.opts.onView(this.pitch, this.yaw);
    }

    setView(pitch, yaw, roll = 0) {
      if (this.R) {
        this.setOrient(M3.euler(pitch, yaw, roll));
        return;
      }
      this.pitch = this.opts.free ? pitch : clamp(pitch, -CONFIG.VIEW.PITCH_LIMIT, CONFIG.VIEW.PITCH_LIMIT);
      this.yaw = yaw;
      this.applyView();
    }

    setOrient(R) {
      this.R = R.map((row) => row.slice());
      this.applyView();
    }

    /* Rotate the cube around a view axis (x = right, y = up, z = toward the viewer), degrees. */
    rotateView(axis, deg, base = this.R) {
      this.setOrient(M3.mul(M3.rot(axis, deg * DEG), base));
    }

    /* "Down" in cube (model) coordinates for the current view: what an accelerometer would report. */
    gravity() {
      if (this.R) return [-this.R[1][0], -this.R[1][1], -this.R[1][2]];
      const p = this.pitch * DEG, y = this.yaw * DEG;
      return [Math.sin(p) * Math.sin(y), -Math.cos(p), -Math.sin(p) * Math.cos(y)];
    }

    frameOf(s) {
      const f = FACES[faceOfNormal(s.n)];
      return { R: f.r, U: f.u, N: f.n, C: s.pos };
    }

    layout(anim) {
      if (!this.model) return;
      for (const s of this.model.stickers) {
        let fr = this.frameOf(s);
        if (anim && anim.set.has(s.id)) fr = rotFrame(fr, anim.axis, anim.angle);
        const e = this.els[s.id];
        e.style.transform = cssMatrix(fr, this.unit);
        if (!anim) {
          const { row, col } = slotInfo(s.slot);
          e.dataset.corner = `${row}${col}`;
        }
      }
    }

    layoutCaps(move, angle) {
      const A = V.unit(move.axis);
      const up = move.axis === AXIS.Y ? [0, 0, -1] : [0, 1, 0];
      const mk = (N, C) => ({ R: V.cross(up, N), U: up, N, C });
      const eps = CONFIG.VIEW.CAP_EPS;
      const moving = rotFrame(mk(V.scale(A, -move.layer), V.scale(A, move.layer * eps)), move.axis, angle);
      const still = mk(V.scale(A, move.layer), V.scale(A, -move.layer * eps));
      this.caps[0].style.transform = cssMatrix(moving, this.unit);
      this.caps[1].style.transform = cssMatrix(still, this.unit);
    }

    /* shape(t) -> angle in radians for t = 0..1 (default: an eased quarter turn). */
    animate(token, ms, shape) {
      const { move, q } = tokenInfo(token);
      const set = new Set(this.model.layerOf(move).map((s) => s.id));
      this.caps.forEach((c) => { c.style.display = 'block'; });
      return new Promise((resolve) => {
        const t0 = performance.now();
        const step = (now) => {
          const t = Math.min(1, (now - t0) / ms);
          const angle = shape ? shape(t) : q * ease(t) * Math.PI / 2;
          this.layout({ set, axis: move.axis, angle });
          this.layoutCaps(move, angle);
          if (t < 1) { requestAnimationFrame(step); return; }
          this.caps.forEach((c) => { c.style.display = 'none'; });
          resolve();
        };
        requestAnimationFrame(step);
      });
    }

    render(draw) {
      for (const s of this.model.stickers) {
        const d = draw(s);
        const e = this.els[s.id];
        applyDraw(e, d);
        e.classList.toggle('is-hud', !!d.hud);
        e._lbl.textContent = `M${s.module}·${s.screen}`;
      }
    }

    bindPointer() {
      const VC = CONFIG.VIEW;
      let drag = null;
      this.scene.addEventListener('pointerdown', (ev) => {
        const st = ev.target.closest('.cv-st');
        drag = { x: ev.clientX, y: ev.clientY, pitch: this.pitch, yaw: this.yaw, R: this.R, spin: ev.shiftKey, moved: false, sid: st ? +st.dataset.sid : null };
        this.scene.setPointerCapture(ev.pointerId);
      });
      this.scene.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > VC.CLICK_SLOP_PX) {
          drag.moved = true;
          this.scene.classList.add('is-drag');
        }
        if (!drag.moved) return;
        if (drag.R) {
          /* Tilt like a tray: drag right lowers the right side, drag down lowers the near edge; Shift spins. */
          const k = VC.DRAG_DEG_PER_PX;
          const tilt = drag.spin ? M3.rot(AXIS.Y, dx * k * DEG) : M3.mul(M3.rot(AXIS.Z, -dx * k * DEG), M3.rot(AXIS.X, dy * k * DEG));
          this.setOrient(M3.mul(tilt, drag.R));
          return;
        }
        this.setView(drag.pitch - dy * VC.DRAG_DEG_PER_PX, drag.yaw + dx * VC.DRAG_DEG_PER_PX);
      });
      const end = () => {
        if (!drag) return;
        if (!drag.moved && drag.sid != null && this.opts.onPat) this.opts.onPat(drag.sid);
        drag = null;
        this.scene.classList.remove('is-drag');
      };
      this.scene.addEventListener('pointerup', end);
      this.scene.addEventListener('pointercancel', () => { drag = null; this.scene.classList.remove('is-drag'); });
      this.scene.addEventListener('pointerover', (ev) => {
        if (drag && drag.moved) return;
        const st = ev.target.closest('.cv-st');
        if (this.opts.onHover) this.opts.onHover(st ? +st.dataset.sid : null);
      });
      this.scene.addEventListener('pointerleave', () => this.opts.onHover && this.opts.onHover(null));
    }
  }

  /* ============================== 2D net ================================ */

  class NetView {
    constructor(host, opts = {}) {
      this.opts = opts;
      this.root = el('div', 'cv-net' + (opts.mini ? ' is-mini' : ''));
      host.appendChild(this.root);
      this.cells = [];
      for (let slot = 0; slot < CONFIG.SCREENS; slot++) {
        const { face, row, col } = slotInfo(slot);
        const [c0, r0] = NET_POS[face];
        const cell = el('div', 'cv-cell', '<div class="cv-scr"></div><div class="cv-lbl"></div>');
        cell.style.gridColumn = String(c0 + col + 1);
        cell.style.gridRow = String(r0 + row + 1);
        cell._scr = cell.firstChild;
        cell._lbl = cell.lastChild;
        cell._svg = '';
        this.root.appendChild(cell);
        this.cells.push(cell);
      }
      for (const face of FACE_IDS) {
        const [c0, r0] = NET_POS[face];
        const box = el('div', 'cv-facebox', opts.mini ? '' : `<span title="${FACES[face].name}">${face}</span>`);
        box.style.gridColumn = `${c0 + 1} / span 2`;
        box.style.gridRow = `${r0 + 1} / span 2`;
        this.root.appendChild(box);
      }
      if (opts.onPat) this.root.addEventListener('click', (ev) => {
        const c = ev.target.closest('.cv-cell');
        if (c) opts.onPat(+c.dataset.sid);
      });
      if (opts.onHover) {
        this.root.addEventListener('pointerover', (ev) => {
          const c = ev.target.closest('.cv-cell');
          opts.onHover(c ? +c.dataset.sid : null);
        });
        this.root.addEventListener('pointerleave', () => opts.onHover(null));
      }
    }

    setModel(model) { this.model = model; }

    render(draw) {
      for (let slot = 0; slot < CONFIG.SCREENS; slot++) {
        const s = this.model.at(slot);
        const d = draw(s);
        const cell = this.cells[slot];
        cell.dataset.sid = s.id;
        applyDraw(cell, d);
        cell.classList.toggle('is-hud', !!d.hud);
        cell._lbl.textContent = `M${s.module}·${s.screen}`;
      }
    }
  }

  /* ============================== App shell ============================= */

  class DemoApp {
    constructor(game) {
      this.game = game;
      this.interactive = game.mode === MODE.INTERACTIVE;
      this.packId = game.packs && game.packs.length ? game.packs[0].id : null;
      this.marks = new Map();
      this.queue = [];
      this.running = false;
      this.wiggling = null;
      this.locked = false;
      this.moveCount = 0;
      this.hoverSid = null;
      this.api = this.makeApi();
      this.buildLayout();
      this.loadLevel();
      this.bindKeys();
      this.startTick();
      global.addEventListener('resize', () => this.view3d.resize());
    }

    /* ----- API exposed to the game ----- */
    makeApi() {
      const app = this;
      return {
        CONFIG, FACES, FACE_IDS, EDGE, ROW, V, SVG, slotInfo, slotIndex, faceSlots, ringSlots, quarterInFace, twistSign,
        get model() { return app.model; },
        get packId() { return app.packId; },
        refresh: () => app.commit(),
        redraw: () => app.renderScreens(),
        flash: (sid, kind = 'ok') => app.flash(sid, kind),
        flashSlot: (slot, kind = 'ok') => app.flash(app.model.at(slot).id, kind),
        tone: (freq, ms, delayMs, wave) => Sound.tone(freq, ms, delayMs, wave),
        audio: () => Sound.ensure(),
        gravity: () => app.view3d.gravity(),
        setView: (pitch, yaw, roll) => app.view3d.setView(pitch, yaw, roll),
        orientation: () => app.view3d.R,
        setOrientation: (R) => app.view3d.setOrient(R),
        twist: (tokens) => app.enqueue(Array.isArray(tokens) ? tokens : parseMoves(tokens)),
        twisting: () => app.running,
        wiggle: (token) => app.wiggle(token),
        reset: () => app.loadLevel(),
        M3,
        lock: (on) => { app.locked = !!on; app.syncLock(); },
        isLocked: () => app.locked || app.running,
        hudAt: (slot) => app.hudAt(slot),
      };
    }

    /* ----- Layout ----- */
    buildLayout() {
      const g = this.game;
      document.title = `${g.title} — WowCube ${g.docKind || 'demo'}`;
      document.documentElement.lang = 'en';
      document.body.innerHTML = '';
      const top = el('header', 'cv-top', `<a class="cv-back" href="${g.backHref || 'index.html'}">← All demos</a>
        <div><h1>${g.icon ? g.icon + ' ' : ''}${g.title}</h1><p>${g.tagline || ''}</p></div>`);
      const main = el('main', 'cv-main');
      const stage = el('section', 'cv-stage');
      const side = el('aside', 'cv-side');
      main.append(stage, side);
      document.body.append(top, main);

      const card3d = el('div', 'cv-card');
      const dragHint = this.interactive ? 'drag = tilt the cube' : 'drag to rotate';
      const h3d = el('div', 'cv-card-h', `<span>3D · ${dragHint} · click = pat</span>`);
      const views = el('div', 'cv-views');
      (g.viewPresets || VIEW_PRESETS).forEach((p) => {
        const b = el('button', '', p.label);
        b.onclick = () => this.view3d.setView(p.pitch, p.yaw, p.roll || 0);
        views.appendChild(b);
      });
      h3d.appendChild(views);
      const host3d = el('div', 'cv-host3d');
      card3d.append(h3d, host3d);

      const cardNet = el('div', 'cv-card', '<div class="cv-card-h"><span>Net (2D) · same screens, unfolded</span></div>');
      const hostNet = el('div', 'cv-hostnet');
      cardNet.appendChild(hostNet);
      cardNet.appendChild(el('div', 'cv-hint-line', 'U — up, L — left, F — front, R — right, B — back, D — down. '
        + 'Hover a screen to highlight it in both views. Module numbers (M0–M7) are demo-only.'));
      stage.append(card3d, cardNet);
      this.liveRoots = [host3d, hostNet];

      const hooks = { onPat: (sid) => this.pat(sid), onHover: (sid) => this.hover(sid) };
      this.view3d = new View3D(host3d, {
        ...hooks,
        free: !!g.freeRotate,
        orient: !!g.orientView,
        elev: g.viewElev || 0,
        pitch: g.viewPitch,
        yaw: g.viewYaw,
        onView: () => this.game.onTilt && this.game.onTilt(this.api),
      });
      this.net = new NetView(hostNet, { ...hooks });

      this.statusCard = el('div', 'cv-card', '<div class="cv-card-h"><span>Status</span></div><div class="cv-badge"></div><div class="cv-status-body"></div><div class="cv-meta"></div>');
      this.extraCard = el('div', 'cv-card cv-extra');
      side.append(this.statusCard, this.buildControls(), this.extraCard);

      if (g.showTarget) {
        const tc = el('div', 'cv-card', '<div class="cv-card-h"><span>Goal</span></div>');
        const wrap = el('div', 'cv-target-wrap');
        const h1 = el('div'), h2 = el('div');
        wrap.append(h1, h2);
        tc.appendChild(wrap);
        side.appendChild(tc);
        this.targetViews = {
          view3d: new View3D(h1, { mini: true, unit: CONFIG.VIEW.TARGET_UNIT_PX }),
          net: new NetView(h2, { mini: true }),
        };
      }

      side.appendChild(el('div', 'cv-card cv-info', this.infoHtml()));
      if (g.panel) g.panel(this.extraCard, this.api);
    }

    buildControls() {
      const g = this.game;
      const card = el('div', 'cv-card', `<div class="cv-card-h"><span>${this.interactive ? 'Twist controls' : 'Demo controls'}</span></div>`);
      if (g.packs && g.packs.length > 1) {
        const row = el('div', 'cv-row');
        const sel = el('select');
        g.packs.forEach((p) => sel.appendChild(new Option(p.name, p.id)));
        sel.onchange = () => { this.packId = sel.value; this.loadLevel(); if (g.onPack) g.onPack(this.api); };
        row.appendChild(sel);
        card.appendChild(row);
      }
      const actions = this.interactive
        ? [[['Reset', () => this.loadLevel()]]]
        : [
          [['Scramble level', () => this.loadLevel(), 'is-primary'], ['Goal', () => this.loadSolved()], ['Random', () => this.loadRandom()]],
          [['↶ Undo', () => this.undo()], ['Hint', () => this.hint()], ['Solve ▶', () => this.solve()]],
        ];
      this.buttons = [];
      for (const rowDef of actions) {
        const row = el('div', 'cv-row');
        for (const [label, fn, cls] of rowDef) {
          const b = el('button', cls || '', label);
          b.onclick = fn;
          row.appendChild(b);
          this.buttons.push(b);
        }
        card.appendChild(row);
      }
      const help = g.twistHelp || null;
      const pad = el('div', 'cv-pad' + (help ? ' is-wide' : ''));
      this.padButtons = {};
      for (const id of MOVE_IDS) {
        const item = el('div', 'cv-pad-item', `<span>${MOVES[id].name} · ${id}</span>`);
        for (const tok of [id, id + "'"]) {
          const ccw = tok.endsWith("'");
          const b = el('button', '', ccw ? '↺' : '↻');
          b.title = `${tok} — ${MOVES[id].name}, ${ccw ? 'counter-clockwise' : 'clockwise'}`;
          b.onclick = () => this.enqueue([tok]);
          item.appendChild(b);
          this.padButtons[tok] = b;
          this.buttons.push(b);
        }
        if (help) item.appendChild(el('em', '', help[id] || '—'));
        pad.appendChild(item);
      }
      card.appendChild(pad);
      const toggles = el('div', 'cv-toggles');
      const lbl = el('label', '', '<input type="checkbox"> module numbers');
      lbl.firstChild.onchange = (ev) => document.body.classList.toggle('show-labels', ev.target.checked);
      toggles.appendChild(lbl);
      card.appendChild(toggles);
      card.appendChild(el('div', 'cv-hint-line', 'Keys <b>U D L R F B</b> twist clockwise (looking at that face), <b>Shift</b> — counter-clockwise. '
        + '<b>Arrow keys</b> tilt the cube. Works with any keyboard layout.'));
      this.hintLine = el('div', 'cv-hint-line');
      card.appendChild(this.hintLine);
      return card;
    }

    infoHtml() {
      const g = this.game;
      const howto = (g.howto || []).map(([k, t]) => `<dt>${k}</dt><dd>${t}</dd>`).join('');
      const notes = (g.notes || []).map((n) => `<li>${n}</li>`).join('');
      return `<h3>Idea</h3><p>${g.idea || ''}</p>`
        + (howto ? `<h3>On the cube</h3><dl class="cv-howto">${howto}</dl>` : '')
        + (g.learn ? `<h3>What it teaches</h3><p>${g.learn}</p>` : '')
        + (notes ? `<h3>Implementation notes</h3><ul>${notes}</ul>` : '');
    }

    /* ----- Level setup ----- */
    freshModel() {
      const build = () => (this.game.build ? this.game.build(this.packId, this.api) : null);
      const model = new CubeModel(build());
      this.model = model;
      this.view3d.setModel(model);
      this.net.setModel(model);
      if (this.targetViews) {
        this.targetModel = new CubeModel(build());
        this.targetViews.view3d.setModel(this.targetModel);
        this.targetViews.net.setModel(this.targetModel);
      }
      this.moveCount = 0;
      this.queue = [];
      if (this.game.onReset) this.game.onReset(this.api);
    }

    scrambleOf() {
      const s = this.game.scramble;
      if (s && typeof s === 'object') return s[this.packId] || Object.values(s)[0];
      return s || '';
    }

    loadLevel() {
      if (this.running) return;
      this.freshModel();
      if (!this.interactive) parseMoves(this.scrambleOf()).forEach((t) => this.model.apply(t));
      this.afterLoad();
    }

    loadSolved() {
      if (this.running) return;
      this.freshModel();
      this.afterLoad();
    }

    loadRandom() {
      if (this.running) return;
      this.freshModel();
      let prev = null;
      for (let i = 0; i < CONFIG.RANDOM_SCRAMBLE_LEN; i++) {
        let t;
        do {
          t = MOVE_IDS[Math.floor(Math.random() * MOVE_IDS.length)] + (Math.random() < 0.5 ? "'" : '');
        } while (prev && t === invertToken(prev));
        this.model.apply(t);
        prev = t;
      }
      this.afterLoad();
    }

    afterLoad() {
      this.view3d.layout();
      this.commit();
      if (this.targetViews) {
        const draw = (s) => this.drawFor(this.targetModel, s, new Map());
        this.targetViews.view3d.layout();
        this.targetViews.view3d.render(draw);
        this.targetViews.net.render(draw);
      }
    }

    /* ----- Moves ----- */
    enqueue(tokens) {
      if (this.locked) return;
      this.queue.push(...tokens);
      if (!this.running) this.runQueue();
    }

    /* Half twist: the layer turns a little and springs back; the model does not change. */
    wiggle(token) {
      if (this.running || this.wiggling) return Promise.resolve(false);
      const { q } = tokenInfo(token);
      const A = CONFIG.ANIM;
      const shape = (t) => q * A.WIGGLE_FRAC * Math.sin(Math.PI * t) * Math.PI / 2;
      this.wiggling = this.view3d.animate(token, A.WIGGLE_MS, shape).then(() => {
        this.view3d.layout();
        this.wiggling = null;
        return true;
      });
      return this.wiggling;
    }

    async runQueue() {
      this.running = true;
      while (this.queue.length) {
        if (this.wiggling) await this.wiggling;
        const token = this.queue.shift();
        this.clearHint();
        const ms = this.queue.length ? CONFIG.ANIM.FAST_MS : (this.game.twistMs || CONFIG.ANIM.TWIST_MS);
        await this.view3d.animate(token, ms);
        this.model.apply(token, !this.interactive);
        this.moveCount++;
        this.view3d.layout();
        if (this.interactive && this.game.onTwist) this.game.onTwist(token, this.api);
        this.commit();
      }
      this.running = false;
    }

    undo() {
      const last = this.model.history[this.model.history.length - 1];
      if (last) this.enqueue([invertToken(last)]);
    }

    solve() {
      if (!this.model.history.length) return;
      this.enqueue(this.model.history.slice().reverse().map(invertToken));
    }

    hint() {
      this.clearHint();
      const last = this.model.history[this.model.history.length - 1];
      if (!last) { this.hintLine.textContent = 'The cube is already in its starting (goal) state.'; return; }
      const tok = invertToken(last);
      this.padButtons[tok].classList.add('is-hint');
      this.hintLine.innerHTML = `Hint: next move <b>${tok}</b> (${MOVES[tok[0]].name}). Moves back to goal: ${this.model.history.length}.`;
    }

    clearHint() {
      Object.values(this.padButtons).forEach((b) => b.classList.remove('is-hint'));
      this.hintLine.textContent = '';
    }

    syncLock() {
      const off = this.locked;
      this.buttons.forEach((b) => { b.disabled = off; });
    }

    bindKeys() {
      document.addEventListener('keydown', (ev) => {
        if (ev.target.closest && ev.target.closest('input, textarea, select')) return;
        if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
        const tilt = KEY_TO_TILT[ev.code];
        if (tilt) {
          ev.preventDefault();
          const k = CONFIG.VIEW.KEY_TILT_DEG;
          if (this.view3d.R) {
            /* Arrow keys tilt like a tray: left / right roll, up / down tip away / toward the viewer. */
            this.view3d.rotateView(tilt[1] ? AXIS.Z : AXIS.X, tilt[1] ? -tilt[1] * k : -tilt[0] * k);
            return;
          }
          this.view3d.setView(this.view3d.pitch + tilt[0] * k, this.view3d.yaw + tilt[1] * k);
          return;
        }
        const id = KEY_TO_MOVE[ev.code];
        if (!id) return;
        ev.preventDefault();
        this.enqueue([id + (ev.shiftKey ? "'" : '')]);
      });
    }

    /* Optional animation loop for interactive apps: game.tick(dt, api) returns true when screens changed. */
    startTick() {
      if (!this.game.tick) return;
      let last = performance.now(), lastDraw = 0, lastStatus = 0;
      const loop = (now) => {
        const dt = Math.min(CONFIG.ANIM.MAX_DT_S, (now - last) / 1000);
        last = now;
        const dirty = this.game.tick(dt, this.api);
        if (dirty && !this.running && now - lastDraw >= CONFIG.ANIM.TICK_RENDER_MS) {
          this.renderScreens();
          lastDraw = now;
        }
        if (now - lastStatus >= CONFIG.ANIM.STATUS_MS) {
          this.renderStatus(this.evaluate());
          lastStatus = now;
        }
        requestAnimationFrame(loop);
      };
      requestAnimationFrame(loop);
    }

    /* ----- Rendering ----- */
    hudAt(slot) { return this.game.hud ? this.game.hud(slot, this.api) : null; }

    drawFor(model, s, marks) {
      const info = slotInfo(s.slot);
      if (this.game.paint) {
        const ctx = { slot: s.slot, ...info, sticker: s, model, api: this.api };
        return { paint: (g) => this.game.paint(g, ctx), hud: false };
      }
      if (this.game.screen) {
        return { svg: this.game.screen({ slot: s.slot, ...info, sticker: s, model, api: this.api }) || SVG.blank(), hud: false };
      }
      const hud = this.game.hud ? this.game.hud(s.slot, this.api, model) : null;
      if (hud != null) return { svg: hud, hud: true };
      const ctx = {
        sticker: s, content: s.content, rot: model.rotOf(s), slot: s.slot,
        face: info.face, row: info.row, col: info.col, mark: marks.get(s.id), model, api: this.api,
      };
      return { svg: this.game.render(ctx) || SVG.blank(), hud: false };
    }

    evaluate() {
      const res = (this.game.evaluate && this.game.evaluate(this.api)) || {};
      this.marks = res.marks instanceof Map ? res.marks : new Map(Object.entries(res.marks || {}).map(([k, v]) => [+k, v]));
      return res;
    }

    renderScreens() {
      const draw = (s) => this.drawFor(this.model, s, this.marks);
      this.view3d.render(draw);
      this.net.render(draw);
    }

    commit() {
      const res = this.evaluate();
      if (!this.interactive && this.model.isHome()) this.model.history = [];
      this.renderScreens();
      this.renderStatus(res);
      if (this.hoverSid != null) this.hover(this.hoverSid);
    }

    renderStatus(res) {
      const badge = this.statusCard.querySelector('.cv-badge');
      const text = res.badge || (this.interactive ? '' : res.solved ? 'Goal reached' : 'In progress');
      badge.textContent = text;
      badge.style.display = text ? '' : 'none';
      badge.classList.toggle('is-ok', !!res.solved);
      const body = this.statusCard.querySelector('.cv-status-body');
      const html = res.html || '';
      if (body._html !== html) { body.innerHTML = html; body._html = html; }
      this.statusCard.querySelector('.cv-meta').textContent = this.interactive
        ? `Twists: ${this.moveCount}`
        : `Moves made: ${this.moveCount} · moves back to goal: ${this.model.history.length}`;
    }

    each(sid, fn) {
      for (const root of this.liveRoots) root.querySelectorAll(`[data-sid="${sid}"]`).forEach(fn);
    }

    hover(sid) {
      for (const root of this.liveRoots) root.querySelectorAll('.is-hl').forEach((e) => e.classList.remove('is-hl'));
      this.hoverSid = sid;
      if (sid != null) this.each(sid, (e) => e.classList.add('is-hl'));
    }

    flash(sid, kind) {
      const cls = 'is-flash-' + kind;
      this.each(sid, (e) => {
        e.classList.add(cls);
        setTimeout(() => e.classList.remove(cls), CONFIG.ANIM.FLASH_MS);
      });
    }

    pat(sid) {
      const s = this.model.stickers[sid];
      const hud = !this.game.screen && !this.game.paint && this.hudAt(s.slot) != null;
      const info = slotInfo(s.slot);
      const handled = this.game.onPat ? this.game.onPat({ sticker: s, slot: s.slot, ...info, hud }, this.api) : false;
      if (!handled) this.flash(sid, 'pat');
    }
  }

  /* ============================== Exports =============================== */

  global.CubeDemo = {
    CONFIG, MODE, FACES, FACE_IDS, EDGE, ROW, MOVES, V, SVG, CV, SurfaceGrid, paintParticles,
    slotIndex, slotInfo, faceSlots, ringSlots, parseMoves, invertToken, quarterInFace, twistSign,
    CubeModel, M3,
    mount: (game) => new DemoApp(game).api,
  };
})(window);
