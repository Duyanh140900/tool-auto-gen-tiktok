// API client cho giao diện web. Realtime đi qua WebSocket,
// các endpoint khác dùng fetch thông thường qua Next.js rewrite (/api/*).
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

export function buildApiBase(): string {
  return API_BASE_URL;
}

function buildUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "detail" in payload
        ? String(
            (payload as { detail?: unknown }).detail ?? `HTTP ${response.status}`,
          )
        : typeof payload === "string" && payload.trim()
        ? payload
        : `HTTP ${response.status}`;

    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  return parseResponse<T>(response);
}

export type SettingsResponse = {
  output_dir: string;
  final_output_dir: string;
  itera102_voice_id: string;
  itera102_provider: string;
  itera102_model_id: string;
  itera102_language_code: string;
  itera102_speed: number;
  itera102_stability: number;
  itera102_similarity_boost: number;
  itera102_style: number;
  itera102_use_speaker_boost: boolean;
  edge_tts_voice: string;
  edge_tts_speed: string;
  itera102_api_key_configured: boolean;
  llm_api_key_configured: boolean;
  custom_logo_path?: string;
  custom_card_bg_path?: string;
  custom_nhay_path?: string;
  custom_black_bg_path?: string;
  custom_style1_logo_path?: string;
  custom_style1_card_bg_path?: string;
  custom_style1_nhay_path?: string;
  custom_style1_black_bg_path?: string;
  custom_style2_logo_path?: string;
  custom_style2_card_bg_path?: string;
  custom_style2_nhay_path?: string;
  custom_style2_black_bg_path?: string;
  custom_style3_logo_path?: string;
  custom_style3_card_bg_path?: string;
  custom_style3_nhay_path?: string;
  custom_style3_black_bg_path?: string;
};

export type VoiceItem = {
  index: number;
  name: string;
  voice_id: string;
  active: boolean;
};

export type VoicesResponse = {
  voices: VoiceItem[];
};

// Kết quả thêm sản phẩm của video nguồn vào Showcase (src/showcase.py)
export type ShowcaseProductResult = {
  product: string;
  status: "thanh_cong" | "da_co" | "thu" | "loi" | string;
  note: string;
};

export type ShowcaseState = {
  status: "queued" | "running" | "done" | "error" | "cancelled" | string;
  dry: boolean;
  message: string;
  results: ShowcaseProductResult[];
  updated_at?: string;
};

export type ShowcaseDeviceResponse = {
  ok: boolean;
  serial?: string | null;
  model?: string | null;
  package?: string;
  error?: string;
};

// Kết quả đăng hẹn giờ TikTok Studio (src/tiktok_poster.py)
export type PostState = {
  status: "queued" | "running" | "scheduled" | "unverified" | "waiting" | "thu" | "error" | "cancelled" | string;
  message: string;
  dry: boolean;
  product?: string;
  short_name?: string;
  slot?: string; // "2026-11-05T08:00"
};

export type PostScheduleSummary = {
  path: string;
  studio_last_slot: string | null; // mốc hẹn muộn nhất đọc từ màn Posts của TikTok Studio
  studio_checked_at: string | null;
  last_slot: string | null;
  next_slot: string;
  next_slot_within_horizon: boolean;
  max_days_ahead: number;
  scheduled_count: number;
  waiting_count: number;
  error_count: number;
  flush_running?: boolean;
  backlog_count?: number; // video đã gen, còn file, chưa hẹn
};

export type BatchResultItem = {
  index: number;
  url: string;
  product_name_hint?: string | null;
  custom_script?: string | null;
  video_info?: Record<string, unknown> | null;
  script?: Record<string, unknown> | null;
  tts?: Record<string, unknown> | null;
  merge?: Record<string, unknown> | null;
  capcut?: Record<string, unknown> | null;
  showcase?: ShowcaseState | null;
  post?: PostState | null;
  status: string;
  error?: string | null;
  video_path?: string | null;
  script_path?: string | null;
  audio_path?: string | null;
  final_video_path?: string | null;
};

export type MontageSnapshot = {
  urls: string[];
  script: string;
  voice_id?: string | null;
  seed?: number | null;
  status: string;
  message?: string | null;
  error?: string | null;
  downloaded_paths?: string[];
  audio_path?: string | null;
  final_video_path?: string | null;
  manifest_path?: string | null;
  audio_duration?: number | null;
  clips?: Array<Record<string, unknown>>;
};

export type JobSnapshot = {
  job_id: string;
  created_at?: string | null;
  status: string;
  mode?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  items: BatchResultItem[];
  montage?: MontageSnapshot | null;
};

export type ResultsResponse = {
  items: Array<{
    file_name: string;
    file_path: string;
    size_bytes: number;
    modified_at: string;
    download_url: string;
  }>;
};

export type BatchPayload = {
  items: Array<{
    url: string;
    product_name_hint?: string;
    custom_script?: string;
    video_shift_ratio?: number;
    video_scale?: number;
    voice_id?: string;
    style?: string;
    script_theme?: string;
  }>;
  max_concurrent?: number;
  default_voice_id?: string;
  default_style?: string;
  auto_showcase?: boolean;     // gen xong thì thêm sản phẩm vào Showcase
  showcase_dry?: boolean;
  auto_post?: boolean;         // sau Showcase thì đăng hẹn giờ TikTok Studio
  post_dry?: boolean;
  post_delete_after?: boolean; // hẹn xong thì chuyển video vào Thùng rác
  script_theme?: string;       // chủ đề kịch bản AI (vd ngày lễ); bỏ trống = AI tự chọn
};

export type MontagePayload = {
  urls: string[];
  script: string;
  voice_id?: string;
  seed?: number;
  video_shift_ratio?: number;
  video_scale?: number;
  mode?: "live" | "mock";
};

export type SettingsUpdatePayload = {
  final_output_dir?: string;
  itera102_voice_id?: string;
  itera102_speed?: number;
  itera102_stability?: number;
  itera102_similarity_boost?: number;
  itera102_style?: number;
  itera102_use_speaker_boost?: boolean;
  custom_logo_path?: string;
  custom_card_bg_path?: string;
  custom_nhay_path?: string;
  custom_black_bg_path?: string;
  custom_style1_logo_path?: string;
  custom_style1_card_bg_path?: string;
  custom_style1_nhay_path?: string;
  custom_style1_black_bg_path?: string;
  custom_style2_logo_path?: string;
  custom_style2_card_bg_path?: string;
  custom_style2_nhay_path?: string;
  custom_style2_black_bg_path?: string;
  custom_style3_logo_path?: string;
  custom_style3_card_bg_path?: string;
  custom_style3_nhay_path?: string;
  custom_style3_black_bg_path?: string;
};

export type AutoGenItem = {
  url: string;
  product_name_hint?: string;
  custom_script?: string;
  overlay_text?: string;
  video_shift_ratio?: number;
  video_scale?: number;
  style?: string;
  script_theme?: string;
};

export type AutoGenPayload = {
  mode: "review" | "montage";
  items?: AutoGenItem[];   // review mode
  urls?: string[];         // montage mode
  script?: string;         // montage script / optional per-item override
  voice_id?: string;
  seed?: number;
  video_shift_ratio?: number;
  video_scale?: number;
  style?: string;          // "style1", "style2", or "style3"
  mode_pipeline?: "live" | "mock";
  auto_showcase?: boolean; // gen xong thì thêm sản phẩm vào Showcase (review mode)
  showcase_dry?: boolean;
  auto_post?: boolean;     // sau Showcase thì đăng hẹn giờ TikTok Studio
  post_dry?: boolean;
  post_delete_after?: boolean; // hẹn xong thì chuyển video vào Thùng rác
  script_theme?: string;   // chủ đề kịch bản AI (review mode); bỏ trống = AI tự chọn
};

export type ProfileAiVideoPayload = {
  profile_url: string;
  video_shift_ratio?: number;
  video_scale?: number;
  style?: string;
  voice_id?: string;
  mode_pipeline?: "live" | "mock";
  max_videos?: number;
  force_rerun_all?: boolean;
  auto_showcase?: boolean;
  showcase_dry?: boolean;
  auto_post?: boolean;     // sau Showcase thì đăng hẹn giờ TikTok Studio
  post_dry?: boolean;
  post_delete_after?: boolean; // hẹn xong thì chuyển video vào Thùng rác
  script_theme?: string;   // chủ đề kịch bản AI (vd ngày lễ); bỏ trống = AI tự chọn
};

export type ProfileAiVideoResponse = {
  status: "started" | "skipped_all";
  message: string;
  profile_url: string;
  crawled_count?: number;
  skipped_count?: number;
  queued_count?: number;
  manifest_path?: string;
  job: JobSnapshot;
};

export type ProfileAiVideoLogResponse = {
  manifest_path: string;
  log: {
    profile_url?: string;
    updated_at?: string;
    videos: Record<string, {
      url: string;
      video_id?: string | null;
      profile_url?: string;
      product_name?: string | null;
      status: string;
      error?: string | null;
      final_video_path?: string | null;
      crawled_at?: string;
      started_at?: string;
      completed_at?: string;
      updated_at?: string;
    }>;
  };
  total_logged: number;
};

// Setting form /ai-video lưu ở backend để bot Telegram chạy y như nút Chạy
export type AiVideoDefaults = {
  video_shift_ratio: number;
  video_scale: number;
  voice_id: string;
  style: "style1" | "style2" | "style3";
  auto_showcase: boolean;
  showcase_dry: boolean;
  auto_post: boolean;
  post_dry: boolean;
  post_delete_after: boolean;
  script_theme: string;
};

export const api = {
  getSettings() {
    return apiFetch<SettingsResponse>("/api/settings");
  },
  listVoices() {
    return apiFetch<VoicesResponse>("/api/voices");
  },
  getResults() {
    return apiFetch<ResultsResponse>("/api/results");
  },
  getJob() {
    return apiFetch<JobSnapshot | { job: JobSnapshot | null }>("/api/job");
  },
  createBatch(payload: BatchPayload) {
    return apiFetch<JobSnapshot>("/api/batch", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getAiVideoDefaults() {
    return apiFetch<AiVideoDefaults & { saved: boolean }>("/api/ai-video/defaults");
  },
  saveAiVideoDefaults(payload: AiVideoDefaults) {
    return apiFetch<AiVideoDefaults>("/api/ai-video/defaults", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createMontage(payload: MontagePayload) {
    return apiFetch<JobSnapshot>("/api/montage", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  autoGen(payload: AutoGenPayload) {
    return apiFetch<JobSnapshot>("/api/auto-gen", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  createProfileAiVideo(payload: ProfileAiVideoPayload) {
    return apiFetch<ProfileAiVideoResponse>("/api/profile-ai-video", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getProfileAiVideoLog() {
    return apiFetch<ProfileAiVideoLogResponse>("/api/profile-ai-video/log");
  },
  checkShowcaseDevice() {
    return apiFetch<ShowcaseDeviceResponse>("/api/showcase/device");
  },
  getPostSchedule() {
    return apiFetch<PostScheduleSummary>("/api/post-schedule");
  },
  checkPostStudio() {
    return apiFetch<PostScheduleSummary>("/api/post-schedule/check-studio", { method: "POST" });
  },
  postBacklog(payload: { post_dry?: boolean; post_delete_after?: boolean }) {
    return apiFetch<JobSnapshot>("/api/post-backlog", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  flushPostSchedule() {
    return apiFetch<{ ok: boolean }>("/api/post-schedule/flush", { method: "POST" });
  },
  pauseJob() {
    return apiFetch<{ ok: boolean; snapshot: JobSnapshot }>("/api/job/pause", {
      method: "POST",
    });
  },
  resumeJob() {
    return apiFetch<{ ok: boolean; snapshot: JobSnapshot }>("/api/job/resume", {
      method: "POST",
    });
  },
  cancelJob() {
    return apiFetch<{ ok: boolean; snapshot: JobSnapshot }>("/api/job/cancel", {
      method: "POST",
    });
  },
  testRender(payload: { mode: "review" | "montage"; urls: string[]; script: string; duration_sec?: number; video_shift_ratio?: number; video_scale?: number; style?: string }) {
    return apiFetch<{ status: string; message: string; final_video_path?: string }>("/api/test-render", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  saveSettings(payload: SettingsUpdatePayload) {
    return apiFetch<{ ok: true; updated: Record<string, unknown> }>(
      "/api/settings",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },
  pickFolder() {
    return apiFetch<{ path: string | null }>("/api/pick-folder", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },
  pickFile(options?: { title?: string; filter?: string }) {
    return apiFetch<{ path: string | null }>("/api/pick-file", {
      method: "POST",
      body: JSON.stringify(options ?? {}),
    });
  },
  openFolder(path: string) {
    return apiFetch<{ ok: true; path: string }>("/api/open-folder", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },
  revealFile(path: string) {
    return apiFetch<{ ok: true; path: string }>("/api/reveal-file", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },
};
