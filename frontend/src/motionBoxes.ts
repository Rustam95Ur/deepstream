/** Motion regions on a frame pair → red-box geometry for the preview lab. */

export type PixelBox = {
  x: number;
  y: number;
  w: number;
  h: number;
  score: number;
};

export type PreviewBox = {
  x: number;
  y: number;
  w: number;
  h: number;
  cx: number;
  cy: number;
  nx: number;
  ny: number;
  nw: number;
  nh: number;
  score: number;
};

export type PreviewJson = {
  time_s: number;
  frame_width: number;
  frame_height: number;
  boxes: PreviewBox[];
};

const CELL = 8;
const DIFF_SUM = 28;
const CELL_RATIO = 0.22;
const SHAKE_RATIO = 0.45;
const MIN_CELLS = 4;
const PAD = 0.14;
const MAX_BOXES = 6;
const MAX_AREA = 0.55;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function round(n: number, digits: number): number {
  const p = 10 ** digits;
  return Math.round(n * p) / p;
}

function gap(a: PixelBox, b: PixelBox): number {
  const dx = Math.max(0, Math.max(a.x, b.x) - Math.min(a.x + a.w, b.x + b.w));
  const dy = Math.max(0, Math.max(a.y, b.y) - Math.min(a.y + a.h, b.y + b.h));
  return Math.hypot(dx, dy);
}

function union(a: PixelBox, b: PixelBox): PixelBox {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const r = Math.max(a.x + a.w, b.x + b.w);
  const bo = Math.max(a.y + a.h, b.y + b.h);
  return { x, y, w: r - x, h: bo - y, score: Math.max(a.score, b.score) };
}

function mergeClose(boxes: PixelBox[], gapPx: number): PixelBox[] {
  let list = boxes.slice();
  let changed = true;
  while (changed) {
    changed = false;
    const next: PixelBox[] = [];
    const used = new Array<boolean>(list.length).fill(false);
    for (let i = 0; i < list.length; i++) {
      if (used[i]) continue;
      let cur = list[i];
      for (let j = i + 1; j < list.length; j++) {
        if (used[j]) continue;
        if (gap(cur, list[j]) <= gapPx) {
          cur = union(cur, list[j]);
          used[j] = true;
          changed = true;
        }
      }
      next.push(cur);
    }
    list = next;
  }
  return list;
}

function padBox(box: PixelBox, frameW: number, frameH: number): PixelBox {
  const px = box.w * PAD;
  const py = box.h * PAD;
  const x = clamp(box.x - px, 0, frameW);
  const y = clamp(box.y - py, 0, frameH);
  const r = clamp(box.x + box.w + px, 0, frameW);
  const b = clamp(box.y + box.h + py, 0, frameH);
  return { x, y, w: Math.max(1, r - x), h: Math.max(1, b - y), score: box.score };
}

export function detectMotion(
  prev: Uint8ClampedArray,
  curr: Uint8ClampedArray,
  width: number,
  height: number,
): PixelBox[] {
  if (width < CELL * 2 || height < CELL * 2) return [];
  if (prev.length < width * height * 4 || curr.length < width * height * 4) return [];

  const cols = Math.ceil(width / CELL);
  const rows = Math.ceil(height / CELL);
  const active = new Uint8Array(cols * rows);
  const cellScore = new Float32Array(cols * rows);
  let activeCount = 0;

  for (let cy = 0; cy < rows; cy++) {
    for (let cx = 0; cx < cols; cx++) {
      const x0 = cx * CELL;
      const y0 = cy * CELL;
      const x1 = Math.min(width, x0 + CELL);
      const y1 = Math.min(height, y0 + CELL);
      let changed = 0;
      let total = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = (y * width + x) * 4;
          const d =
            Math.abs(curr[i] - prev[i]) +
            Math.abs(curr[i + 1] - prev[i + 1]) +
            Math.abs(curr[i + 2] - prev[i + 2]);
          if (d > DIFF_SUM) changed++;
          total++;
        }
      }
      const ratio = total ? changed / total : 0;
      if (ratio >= CELL_RATIO) {
        const idx = cy * cols + cx;
        active[idx] = 1;
        cellScore[idx] = ratio;
        activeCount++;
      }
    }
  }

  if (!activeCount || activeCount / (cols * rows) >= SHAKE_RATIO) return [];

  const seen = new Uint8Array(active.length);
  const boxes: PixelBox[] = [];
  const stack: number[] = [];

  for (let i = 0; i < active.length; i++) {
    if (!active[i] || seen[i]) continue;
    stack.push(i);
    seen[i] = 1;
    let minC = cols;
    let minR = rows;
    let maxC = 0;
    let maxR = 0;
    let sum = 0;
    let n = 0;
    while (stack.length) {
      const idx = stack.pop();
      if (idx === undefined) break;
      const r = Math.floor(idx / cols);
      const c = idx - r * cols;
      if (c < minC) minC = c;
      if (r < minR) minR = r;
      if (c > maxC) maxC = c;
      if (r > maxR) maxR = r;
      sum += cellScore[idx];
      n++;
      const neighbors = [idx - 1, idx + 1, idx - cols, idx + cols];
      for (const ni of neighbors) {
        if (ni < 0 || ni >= active.length || seen[ni] || !active[ni]) continue;
        const nr = Math.floor(ni / cols);
        const nc = ni - nr * cols;
        if (Math.abs(nr - r) + Math.abs(nc - c) !== 1) continue;
        seen[ni] = 1;
        stack.push(ni);
      }
    }
    if (n < MIN_CELLS) continue;
    boxes.push({
      x: minC * CELL,
      y: minR * CELL,
      w: (maxC - minC + 1) * CELL,
      h: (maxR - minR + 1) * CELL,
      score: n ? sum / n : 0,
    });
  }

  const frameArea = width * height;
  const merged = mergeClose(boxes, CELL * 1.5)
    .map((box) => padBox(box, width, height))
    .filter((box) => (box.w * box.h) / frameArea <= MAX_AREA);

  merged.sort((a, b) => b.score * b.w * b.h - a.score * a.w * a.h);
  return merged.slice(0, MAX_BOXES);
}

export function scaleBoxes(
  boxes: PixelBox[],
  fromW: number,
  fromH: number,
  toW: number,
  toH: number,
): PixelBox[] {
  if (!fromW || !fromH || !toW || !toH) return [];
  const sx = toW / fromW;
  const sy = toH / fromH;
  return boxes.map((box) => {
    const x = clamp(Math.round(box.x * sx), 0, Math.max(0, toW - 1));
    const y = clamp(Math.round(box.y * sy), 0, Math.max(0, toH - 1));
    const w = clamp(Math.round(box.w * sx), 1, toW - x);
    const h = clamp(Math.round(box.h * sy), 1, toH - y);
    return { x, y, w, h, score: box.score };
  });
}

export function strokeBoxes(
  ctx: CanvasRenderingContext2D,
  boxes: PixelBox[],
  frameWidth: number,
): void {
  const line = Math.max(3, Math.round(frameWidth / 480));
  ctx.lineJoin = "miter";
  for (const box of boxes) {
    const x = box.x + line / 2;
    const y = box.y + line / 2;
    const w = Math.max(0, box.w - line);
    const h = Math.max(0, box.h - line);
    ctx.lineWidth = line + 2;
    ctx.strokeStyle = "rgba(0,0,0,0.65)";
    ctx.strokeRect(x, y, w, h);
    ctx.lineWidth = line;
    ctx.strokeStyle = "#ff1a1a";
    ctx.strokeRect(x, y, w, h);
  }
}

export function toPreviewJson(args: {
  timeS: number;
  frameWidth: number;
  frameHeight: number;
  boxes: PixelBox[];
}): PreviewJson {
  const fw = args.frameWidth;
  const fh = args.frameHeight;
  const boxes =
    fw > 0 && fh > 0
      ? args.boxes.map((box) => ({
          x: Math.round(box.x),
          y: Math.round(box.y),
          w: Math.round(box.w),
          h: Math.round(box.h),
          cx: Math.round(box.x + box.w / 2),
          cy: Math.round(box.y + box.h / 2),
          nx: round(box.x / fw, 4),
          ny: round(box.y / fh, 4),
          nw: round(box.w / fw, 4),
          nh: round(box.h / fh, 4),
          score: round(box.score, 3),
        }))
      : [];
  return {
    time_s: round(args.timeS, 3),
    frame_width: fw,
    frame_height: fh,
    boxes,
  };
}
