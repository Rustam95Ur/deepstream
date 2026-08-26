import type { NodeSettings } from "./types";

export type TriggerProfileKey = "presence" | "convergence" | "vif" | "stream_silent";

export function ensureTriggerProfiles(settings: NodeSettings): NodeSettings {
  const profiles = { ...(settings.trigger_thresholds || {}) };
  const base = settings;
  profiles.presence = {
    presence_min_people: base.presence_min_people,
    presence_sustain_s: base.presence_sustain_s,
    cooldown_s: profiles.presence?.cooldown_s ?? base.cooldown_s,
    ...profiles.presence,
  };
  profiles.convergence = {
    min_tracks: base.min_tracks,
    converge_dist_bh: base.converge_dist_bh,
    speed_thresh_bh: base.speed_thresh_bh,
    sustain_s: base.sustain_s,
    cooldown_s: profiles.convergence?.cooldown_s ?? base.cooldown_s,
    ...profiles.convergence,
  };
  profiles.vif = {
    vif_iou_thresh: base.vif_iou_thresh,
    vif_sustain_s: base.vif_sustain_s,
    cooldown_s: profiles.vif?.cooldown_s ?? base.cooldown_s,
    ...profiles.vif,
  };
  profiles.stream_silent = {
    stream_silent_s: base.stream_silent_s,
    cooldown_s: profiles.stream_silent?.cooldown_s ?? base.cooldown_s,
    ...profiles.stream_silent,
  };
  return { ...settings, trigger_thresholds: profiles };
}

export function profileField(
  settings: NodeSettings,
  kind: TriggerProfileKey,
  key: string,
): number {
  const raw = settings.trigger_thresholds?.[kind]?.[key];
  if (raw === undefined || raw === null || raw === "") {
    return 0;
  }
  return Number(raw);
}

export function setProfileField(
  settings: NodeSettings,
  kind: TriggerProfileKey,
  key: string,
  value: number,
) {
  if (!settings.trigger_thresholds) settings.trigger_thresholds = {};
  if (!settings.trigger_thresholds[kind]) settings.trigger_thresholds[kind] = {};
  settings.trigger_thresholds[kind][key] = value;
}
