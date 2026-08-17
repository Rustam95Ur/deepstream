import type { Camera } from "./types";

/** Same integers as Campus CameraStreamProtocolChoices / CameraUsageModuleChoices. */
export const STREAM_PROTOCOLS = [
  { value: 2, label: "RTSP ссылка" },
  { value: 1, label: "ONVIF" },
] as const;

export const USAGE_MODULES = [
  { value: 1, label: "Вовлеченность" },
  { value: 2, label: "Инциденты" },
  { value: 3, label: "Посещаемость" },
] as const;

export interface CameraProfile {
  stream_protocol: number;
  resolution_width: number;
  resolution_height: number;
  fps: number;
  allow_preprocessing: boolean;
  usage_modules: number[];
}

function num(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function cameraProfile(cam?: Pick<Camera, "meta"> | null): CameraProfile {
  const meta = cam?.meta ?? {};
  const modules = Array.isArray(meta.usage_modules)
    ? meta.usage_modules.map((item) => Number(item)).filter((item) => Number.isFinite(item))
    : [];
  return {
    stream_protocol: num(meta.stream_protocol, 2),
    resolution_width: num(meta.resolution_width, 1280),
    resolution_height: num(meta.resolution_height, 720),
    fps: num(meta.fps, 25),
    allow_preprocessing: Boolean(meta.allow_preprocessing),
    usage_modules: modules,
  };
}

export function cameraProfileMeta(profile: CameraProfile): Record<string, unknown> {
  return {
    stream_protocol: Number(profile.stream_protocol) || 2,
    resolution_width: Number(profile.resolution_width) || 1280,
    resolution_height: Number(profile.resolution_height) || 720,
    fps: Number(profile.fps) || 25,
    allow_preprocessing: Boolean(profile.allow_preprocessing),
    usage_modules: [...profile.usage_modules],
  };
}

export function resolutionLabel(cam: Pick<Camera, "meta">): string {
  const p = cameraProfile(cam);
  return `${p.resolution_width}×${p.resolution_height}`;
}
