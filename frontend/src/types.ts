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
  triggers_url: string;
  triggers_timeout_sec: number;
  enable_http_sink: boolean;
  enable_log_sink: boolean;
  enable_clip_record: boolean;
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
  enabled_triggers: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface CameraList {
  node_id: string;
  cameras: Camera[];
  updated_at: string | null;
  next_cursor?: string | null;
}

export interface CameraTestBatch {
  cameras: Camera[];
  created: number;
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

export interface CameraSkip {
  camera_id: string;
  name: string;
  reason: string;
}

export interface LogLine {
  ts?: string | null;
  level: string;
  logger: string;
  message: string;
}

export interface WorkerStatus {
  running: boolean;
  available: boolean;
  detail: string;
  last_started_at: string | null;
  last_error: string;
  camera_ids: string[];
  reload_pending?: boolean;
  max_streams?: number;
  skipped?: CameraSkip[];
  recent_errors?: LogLine[];
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
  id: string;
  event_id: string;
  sink: string;
  url: string;
  status: string;
  http_status: number | null;
  error: string;
  created_at: string;
}

export interface Clip {
  url: string;
  bucket: string;
  key: string;
}

export interface TriggerEvent {
  event_id: string;
  camera_id: string;
  camera_name: string;
  trigger_type: string;
  category: string;
  evidence: Record<string, unknown>;
  clip: Clip;
  video_url: string;
  video_bucket: string;
  video_key: string;
  created_at: string;
}

export interface Webhook {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  login: string;
  auth_configured: boolean;
  timeout_sec: number;
  max_retries: number;
  created_at: string;
  updated_at: string;
}

export interface WebhookIn {
  name: string;
  url: string;
  enabled: boolean;
  login: string;
  password?: string | null;
  timeout_sec: number;
  max_retries: number;
}

export interface OutboundJob {
  id: string;
  event_id: string;
  webhook_id: string;
  url: string;
  attempts: number;
  max_attempts: number;
  status: string;
  last_error: string;
  http_status: number | null;
  next_attempt_at: string;
  created_at: string;
  updated_at: string;
}

export interface RingCameraHealth {
  camera_id: string;
  name: string;
  alive: boolean;
  stalled: boolean;
  last_segment_age_s: number | null;
  restarts: number;
  codec: string;
  last_error?: string;
}

export interface VideoHealth {
  status: string;
  gst_available: boolean;
  clip_record: boolean;
  ring_running: boolean;
  pipeline: WorkerStatus;
  cameras: RingCameraHealth[];
  recent_errors?: LogLine[];
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
