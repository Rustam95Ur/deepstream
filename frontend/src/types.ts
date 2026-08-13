export interface Session {
  authenticated: boolean;
  setup: boolean;
  user_id: string;
  email: string;
  name: string;
  node_id: string;
  node_name: string;
}

export interface NodeSettings {
  node_id: string;
  node_name: string;
  api_token: string;
  cameras_url: string;
  cameras_poll_sec: number;
  triggers_url: string;
  triggers_timeout_sec: number;
  enable_http_sink: boolean;
  enable_log_sink: boolean;
  trigger_mode: string;
  enabled_triggers: string[];
  min_tracks: number;
  converge_dist_bh: number;
  speed_thresh_bh: number;
  sustain_s: number;
  cooldown_s: number;
  presence_min_people: number;
  presence_sustain_s: number;
  vif_iou_thresh: number;
  vif_sustain_s: number;
  clip_pre_s: number;
  clip_post_s: number;
  infer_interval: number;
  conf_threshold: number;
  reconnect_s: number;
  stream_silent_s: number;
  mux_width: number;
  mux_height: number;
  person_class_id: number;
  detector_model: string;
  auto_start_pipeline: boolean;
  max_streams: number;
}

export interface Camera {
  id: string;
  name: string;
  main_uri: string;
  enabled: boolean;
  external_id: string;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CameraList {
  node_id: string;
  cameras: Camera[];
  updated_at: string | null;
  next_cursor?: string | null;
}

export interface CameraQuery {
  q?: string;
  enabled?: boolean;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}

export interface UserQuery {
  q?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}

export interface WorkerStatus {
  running: boolean;
  available: boolean;
  detail: string;
  last_started_at: string | null;
  last_error: string;
  camera_ids: string[];
}

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface UserList {
  users: User[];
  next_cursor?: string | null;
  total?: number;
}

export interface HistoryPage<T> {
  items: T[];
  next_cursor?: string | null;
}

export interface SendEvent {
  event_id: string;
  sink: string;
  url: string;
  status: string;
  http_status: number | null;
  error: string;
  created_at: string;
}

export interface HistoryQuery {
  since?: string;
  until?: string;
  camera_id?: string;
  trigger_type?: string;
  category?: string;
  event_id?: string;
  status?: string;
  sink?: string;
  limit?: number;
  cursor?: string;
}

export interface TriggerEvent {
  event_id: string;
  camera_id: string;
  trigger_type: string;
  category: string;
  evidence: Record<string, unknown>;
  created_at: string;
}
