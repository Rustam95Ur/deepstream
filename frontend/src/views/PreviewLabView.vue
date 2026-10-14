<script setup lang="ts">
import { nextTick, onUnmounted, ref } from "vue";
import {
  detectMotion,
  scaleBoxes,
  strokeBoxes,
  toPreviewJson,
  type PixelBox,
} from "../motionBoxes";

const fileInput = ref<HTMLInputElement | null>(null);
const videoRef = ref<HTMLVideoElement | null>(null);
const overlayRef = ref<HTMLCanvasElement | null>(null);

const fileName = ref("");
const videoUrl = ref("");
const previewUrl = ref("");
const jsonText = ref("");
const status = ref("");
const errorText = ref("");
const scanning = ref(false);

let scanGen = 0;
let scanQueue: Promise<void> = Promise.resolve();
let liveRaf = 0;
let prevFrame: ImageData | null = null;
let liveAt = 0;
let ignoreSeeked = false;
let scanDrivesPlay = false;

type Hit = {
  timeS: number;
  boxes: PixelBox[];
  aw: number;
  ah: number;
  score: number;
  shot: HTMLCanvasElement;
};

const analyze = document.createElement("canvas");

function revoke(url: string) {
  if (url.startsWith("blob:")) URL.revokeObjectURL(url);
}

onUnmounted(() => {
  scanGen++;
  cancelAnimationFrame(liveRaf);
  revoke(videoUrl.value);
  revoke(previewUrl.value);
});

function paintOverlay(boxes: PixelBox[]) {
  const video = videoRef.value;
  const canvas = overlayRef.value;
  if (!video || !canvas) return;
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return;
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, w, h);
  strokeBoxes(ctx, boxes, w);
}

function grabFrame(video: HTMLVideoElement): ImageData | null {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;
  const w = 160;
  const h = Math.max(1, Math.round((vh * w) / vw));
  analyze.width = w;
  analyze.height = h;
  const ctx = analyze.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h);
}

function seekTo(video: HTMLVideoElement, time: number): Promise<void> {
  const target = Math.min(Math.max(0, time), Math.max(0, (video.duration || 0) - 0.04));
  if (Math.abs(video.currentTime - target) < 0.03) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("seek"));
    }, 2500);
    const onSeeked = () => {
      cleanup();
      resolve();
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      video.removeEventListener("seeked", onSeeked);
    };
    video.addEventListener("seeked", onSeeked);
    video.currentTime = target;
  });
}

function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

function sampleTimes(duration: number): number[] {
  const span = Math.max(0, duration - 0.08);
  if (span < 0.15) return [0];
  const count = span <= 6 ? Math.max(2, Math.ceil(span / 0.4)) : 16;
  const times: number[] = [];
  for (let i = 0; i < count; i++) times.push((span * (i + 0.5)) / count);
  return times;
}

function waitMeta(video: HTMLVideoElement): Promise<void> {
  if (video.readyState >= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      cleanup();
      if (video.readyState >= 1) resolve();
      else reject(new Error("format"));
    }, 8000);
    const ok = () => {
      cleanup();
      resolve();
    };
    const bad = () => {
      cleanup();
      reject(new Error("format"));
    };
    const cleanup = () => {
      window.clearTimeout(timer);
      video.removeEventListener("loadedmetadata", ok);
      video.removeEventListener("error", bad);
    };
    video.addEventListener("loadedmetadata", ok);
    video.addEventListener("error", bad);
  });
}

function takeShot(video: HTMLVideoElement): HTMLCanvasElement | null {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return null;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, w, h);
  return canvas;
}

function consider(video: HTMLVideoElement, prev: ImageData | null, frame: ImageData, best: Hit | null): Hit | null {
  if (!prev || prev.width !== frame.width || prev.height !== frame.height) return best;
  const found = detectMotion(prev.data, frame.data, frame.width, frame.height);
  const score = found.reduce((sum, box) => sum + box.score * box.w * box.h, 0);
  if (score <= 0 || (best && score <= best.score)) return best;
  const shot = takeShot(video);
  if (!shot) return best;
  return {
    timeS: Number.isFinite(video.currentTime) ? video.currentTime : 0,
    boxes: found,
    aw: frame.width,
    ah: frame.height,
    score,
    shot,
  };
}

async function burnShot(shot: HTMLCanvasElement, boxes: PixelBox[]): Promise<string> {
  const canvas = document.createElement("canvas");
  canvas.width = shot.width;
  canvas.height = shot.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas");
  ctx.drawImage(shot, 0, 0);
  strokeBoxes(ctx, boxes, canvas.width);
  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob(resolve, "image/jpeg", 0.92);
  });
  if (!blob) throw new Error("preview");
  return URL.createObjectURL(blob);
}

function playThrough(video: HTMLVideoElement, gen: number, onFrame: () => void): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    let last = 0;
    let timer = 0;
    const finish = () => {
      if (done) return;
      done = true;
      scanDrivesPlay = false;
      video.pause();
      video.removeEventListener("timeupdate", tick);
      video.removeEventListener("ended", finish);
      window.clearTimeout(timer);
      resolve();
    };
    const tick = () => {
      if (gen !== scanGen) {
        finish();
        return;
      }
      const now = performance.now();
      if (now - last < 100) return;
      last = now;
      onFrame();
      if (video.currentTime > 8) finish();
    };
    timer = window.setTimeout(finish, 9000);
    video.addEventListener("timeupdate", tick);
    video.addEventListener("ended", finish);
    scanDrivesPlay = true;
    void video.play().catch(() => finish());
  });
}

async function scan(video: HTMLVideoElement, gen: number) {
  scanning.value = true;
  ignoreSeeked = true;
  errorText.value = "";
  jsonText.value = "";
  revoke(previewUrl.value);
  previewUrl.value = "";
  try {
    video.pause();
    if (!video.videoWidth || !video.videoHeight) {
      errorText.value = "У ролика нет кадров.";
      return;
    }
    let prev: ImageData | null = null;
    let best: Hit | null = null;
    const absorb = () => {
      const frame = grabFrame(video);
      if (!frame) return;
      best = consider(video, prev, frame, best);
      prev = frame;
    };

    if (Number.isFinite(video.duration) && video.duration > 0) {
      const times = sampleTimes(video.duration);
      for (let i = 0; i < times.length; i++) {
        if (gen !== scanGen) return;
        status.value = `Смотрю кадр ${i + 1} из ${times.length}`;
        try {
          await seekTo(video, times[i]);
        } catch {
          continue;
        }
        if (gen !== scanGen) return;
        await nextPaint();
        absorb();
      }
    } else {
      status.value = "Смотрю ролик…";
      await playThrough(video, gen, absorb);
    }

    if (gen !== scanGen) return;
    const hit = best;
    const boxes = hit ? scaleBoxes(hit.boxes, hit.aw, hit.ah, hit.shot.width, hit.shot.height) : [];
    const shot = hit?.shot ?? takeShot(video);
    if (!shot) {
      errorText.value = "Не удалось снять кадр с этого видео.";
      return;
    }
    if (hit && Number.isFinite(video.duration)) {
      try {
        await seekTo(video, hit.timeS);
        await nextPaint();
      } catch {
        /* preview still uses the saved frame */
      }
    }
    if (gen !== scanGen) return;

    paintOverlay(boxes);
    const url = await burnShot(shot, boxes);
    if (gen !== scanGen) {
      revoke(url);
      return;
    }
    previewUrl.value = url;
    const payload = toPreviewJson({
      timeS: hit?.timeS ?? (Number.isFinite(video.currentTime) ? video.currentTime : 0),
      frameWidth: shot.width,
      frameHeight: shot.height,
      boxes,
    });
    jsonText.value = JSON.stringify(payload, null, 2);
    status.value = boxes.length
      ? `Кадр ${payload.time_s} с · боксов: ${boxes.length} · ${payload.frame_width}×${payload.frame_height}`
      : "Движения в ролике не нашлось — боксов нет.";
  } catch {
    if (gen === scanGen) errorText.value = "Не удалось снять кадр с этого видео.";
  } finally {
    if (gen === scanGen) {
      scanning.value = false;
      ignoreSeeked = false;
    }
  }
}

function onPick(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  const looksVideo = file.type.startsWith("video/") || /\.(mp4|webm|mov|mkv|m4v)$/i.test(file.name);
  if (!looksVideo) {
    errorText.value = "Нужен видеофайл, лучше MP4.";
    return;
  }
  errorText.value = "";
  status.value = "Открываю видео…";
  jsonText.value = "";
  revoke(previewUrl.value);
  previewUrl.value = "";
  const previousVideo = videoUrl.value;
  fileName.value = file.name;
  videoUrl.value = URL.createObjectURL(file);
  const gen = ++scanGen;
  cancelAnimationFrame(liveRaf);
  prevFrame = null;
  scanQueue = scanQueue
    .catch(() => undefined)
    .then(async () => {
      if (gen !== scanGen) return;
      await nextTick();
      revoke(previousVideo);
      const video = videoRef.value;
      if (!video || gen !== scanGen) return;
      try {
        await waitMeta(video);
      } catch {
        if (gen === scanGen) errorText.value = "Браузер не открыл этот формат. Подойдёт MP4 или WebM.";
        return;
      }
      if (gen !== scanGen) return;
      await scan(video, gen);
    });
}

function onPlay() {
  if (scanning.value) {
    if (!scanDrivesPlay) videoRef.value?.pause();
    return;
  }
  prevFrame = null;
  liveAt = 0;
  paintOverlay([]);
  cancelAnimationFrame(liveRaf);
  liveRaf = requestAnimationFrame(loop);
}

function onPause() {
  cancelAnimationFrame(liveRaf);
}

function onSeeked() {
  if (ignoreSeeked || scanning.value || !videoRef.value?.paused) return;
  paintOverlay([]);
}

function onVideoError() {
  if (!scanning.value) errorText.value = "Браузер не открыл этот формат. Подойдёт MP4 или WebM.";
}

function loop() {
  const video = videoRef.value;
  if (!video || video.paused || video.ended) return;
  const now = performance.now();
  if (now - liveAt > 90) {
    const frame = grabFrame(video);
    if (frame && prevFrame && prevFrame.width === frame.width && prevFrame.height === frame.height) {
      const raw = detectMotion(prevFrame.data, frame.data, frame.width, frame.height);
      paintOverlay(scaleBoxes(raw, frame.width, frame.height, video.videoWidth, video.videoHeight));
    }
    prevFrame = frame;
    liveAt = now;
  }
  liveRaf = requestAnimationFrame(loop);
}

function downloadUrl(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}

function downloadPreview() {
  if (previewUrl.value) downloadUrl(previewUrl.value, "incident-preview.jpg");
}

function downloadJson() {
  const blob = new Blob([jsonText.value], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  downloadUrl(url, "incident-boxes.json");
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="stack-lg">
    <section class="card">
      <div class="card-head">
        <h2>Кадр и боксы</h2>
        <p class="lede">
          Загрузите видео инцидента. Страница снимет кадр, где есть движение, нарисует красные квадраты
          и покажет JSON с позицией этих квадратов на картинке.
        </p>
      </div>
      <div class="card-body">
        <div class="pick-row">
          <input
            ref="fileInput"
            type="file"
            accept="video/mp4,video/webm,video/quicktime,video/*"
            hidden
            @change="onPick"
          />
          <button type="button" @click="fileInput?.click()">Загрузить видео</button>
          <span v-if="fileName" class="muted">{{ fileName }}</span>
        </div>
        <p v-if="status" class="lede status-line">{{ status }}</p>
        <p v-if="errorText" class="preview-error">{{ errorText }}</p>
      </div>
    </section>

    <div class="split-2">
      <section class="card">
        <div class="card-head">
          <h2>Превью</h2>
        </div>
        <div class="card-body">
          <img
            v-if="previewUrl"
            :src="previewUrl"
            alt="Кадр инцидента с красными квадратами"
            class="preview-img"
          />
          <p v-else class="muted">После загрузки здесь будет картинка с красными квадратами.</p>
        </div>
        <div v-if="previewUrl" class="card-foot end">
          <button type="button" class="ghost" @click="downloadPreview">Скачать картинку</button>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>Позиция на кадре</h2>
          <p class="lede">
            x, y — левый верхний угол в пикселях, w и h — размер. nx, ny, nw, nh — та же позиция
            долей кадра от 0 до 1. cx, cy — центр квадрата.
          </p>
        </div>
        <div class="card-body">
          <pre v-if="jsonText" class="code-sample">{{ jsonText }}</pre>
          <p v-else class="muted">JSON появится вместе с картинкой.</p>
        </div>
        <div v-if="jsonText" class="card-foot end">
          <button type="button" class="ghost" @click="downloadJson">Скачать JSON</button>
        </div>
      </section>
    </div>

    <section v-if="videoUrl" class="card">
      <div class="card-head">
        <h2>Ролик</h2>
        <p class="lede">При воспроизведении красные квадраты идут за движением в кадре.</p>
      </div>
      <div class="card-body">
        <div class="stage">
          <video
            ref="videoRef"
            :src="videoUrl"
            controls
            playsinline
            muted
            preload="auto"
            @play="onPlay"
            @pause="onPause"
            @seeked="onSeeked"
            @error="onVideoError"
          />
          <canvas ref="overlayRef" class="overlay" />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pick-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.status-line { margin-top: 0.85rem; }
.preview-error { color: var(--err); margin: 0.8rem 0 0; }
.preview-img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  background: #111;
}
.stage {
  position: relative;
  background: #111;
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.stage video,
.stage canvas {
  display: block;
  width: 100%;
  height: auto;
}
.stage canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
