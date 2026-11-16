"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Folder,
  FolderOpen,
  Globe,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  Sparkles,
  Square,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PostBadge, PostOptions, ShowcaseBadge, ShowcaseOptions } from "@/components/workflow/showcase-controls";
import { useJobEvents } from "@/hooks/use-job-events";
import { loadFormMemory, saveFormMemory } from "@/lib/form-memory";
import { ScriptThemeInput } from "@/components/workflow/script-theme-input";
import { toast } from "@/hooks/use-toast";
import {
  api,
  ApiError,
  ProfileAiVideoLogResponse,
  ProfileAiVideoResponse,
  SettingsResponse,
  VoiceItem,
} from "@/lib/api";

function mapSettings(data: SettingsResponse) {
  return {
    finalOutputDir: data.final_output_dir || "",
    itera102VoiceId: data.itera102_voice_id || "",
    style1LogoPath: data.custom_style1_logo_path || data.custom_logo_path || "",
    style1CardBgPath: data.custom_style1_card_bg_path || data.custom_card_bg_path || "",
    style1NhayPath: data.custom_style1_nhay_path || data.custom_nhay_path || "",
    style1BlackBgPath: data.custom_style1_black_bg_path || data.custom_black_bg_path || "",
    style2LogoPath: data.custom_style2_logo_path || "",
    style2CardBgPath: data.custom_style2_card_bg_path || "",
    style2NhayPath: data.custom_style2_nhay_path || "",
    style2BlackBgPath: data.custom_style2_black_bg_path || "",
    style3LogoPath: data.custom_style3_logo_path || "",
    style3CardBgPath: data.custom_style3_card_bg_path || "",
    style3NhayPath: data.custom_style3_nhay_path || "",
    style3BlackBgPath: data.custom_style3_black_bg_path || "",
  };
}

function statusLabel(status?: string | null) {
  switch (status) {
    case "running":
      return "Đang chạy";
    case "paused":
      return "Đang tạm dừng";
    case "cancelled":
      return "Đã dừng hẳn";
    case "done":
    case "completed":
      return "Hoàn thành";
    case "failed":
    case "error":
      return "Lỗi";
    case "pending":
      return "Chờ xử lý";
    default:
      return status || "Sẵn sàng";
  }
}

function statusVariant(status?: string | null): "success" | "warning" | "secondary" | "destructive" {
  switch (status) {
    case "done":
    case "completed":
      return "success";
    case "running":
    case "paused":
      return "warning";
    case "failed":
    case "error":
    case "cancelled":
      return "destructive";
    default:
      return "secondary";
  }
}

const FORM_MEMORY_KEY = "profile-ai-video";

export function ProfileAiVideoScreen() {
  const {
    snapshot,
    status: socketStatus,
    error: socketError,
  } = useJobEvents();

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [settingsStyleTab, setSettingsStyleTab] = useState<"style1" | "style2" | "style3">("style1");

  // Profile URL input
  const [profileUrl, setProfileUrl] = useState("");
  // Default video shift ratio for profile AI Video screen is explicitly 0.25
  const [videoShiftRatio, setVideoShiftRatio] = useState("0.25");
  const [videoScale, setVideoScale] = useState("1.08");
  const [selectedStyle, setSelectedStyle] = useState<"style1" | "style2" | "style3">("style1");
  const [voiceId, setVoiceId] = useState<string>("google-free");
  const [modePipeline, setModePipeline] = useState<"live" | "mock">("live");
  const [forceRerunAll, setForceRerunAll] = useState(false);
  const [maxVideos, setMaxVideos] = useState("0");
  const [autoShowcase, setAutoShowcase] = useState(false);
  const [showcaseDry, setShowcaseDry] = useState(false);
  const [autoPost, setAutoPost] = useState(false);
  const [postDry, setPostDry] = useState(false);
  const [postDeleteAfter, setPostDeleteAfter] = useState(false);
  const [scriptTheme, setScriptTheme] = useState(""); // Chủ đề kịch bản AI, rỗng = AI tự chọn

  // Thông số lần chạy gần nhất (trừ "Chạy lại tất cả" và Mock: chỉ dùng 1 lần)
  type FormMemory = {
    profileUrl: string;
    videoShiftRatio: string;
    videoScale: string;
    selectedStyle: "style1" | "style2" | "style3";
    voiceId: string;
    maxVideos: string;
    autoShowcase: boolean;
    showcaseDry: boolean;
    autoPost: boolean;
    postDry: boolean;
    postDeleteAfter: boolean;
    scriptTheme: string;
  };
  useEffect(() => {
    const m = loadFormMemory<FormMemory>(FORM_MEMORY_KEY);
    if (m.scriptTheme !== undefined) setScriptTheme(m.scriptTheme);
    if (m.profileUrl !== undefined) setProfileUrl(m.profileUrl);
    if (m.videoShiftRatio !== undefined) setVideoShiftRatio(m.videoShiftRatio);
    if (m.videoScale !== undefined) setVideoScale(m.videoScale);
    if (m.selectedStyle) setSelectedStyle(m.selectedStyle);
    if (m.maxVideos !== undefined) setMaxVideos(m.maxVideos);
    if (m.autoShowcase !== undefined) setAutoShowcase(m.autoShowcase);
    if (m.showcaseDry !== undefined) setShowcaseDry(m.showcaseDry);
    if (m.autoPost !== undefined) setAutoPost(m.autoPost);
    if (m.postDry !== undefined) setPostDry(m.postDry);
    if (m.postDeleteAfter !== undefined) setPostDeleteAfter(m.postDeleteAfter);
    // voiceId áp sau khi tải danh sách voice (bootstrap) để không bị ghi đè
  }, []);

  // Settings
  const [settings, setSettings] = useState(() =>
    mapSettings({
      output_dir: "",
      final_output_dir: "",
      itera102_voice_id: "",
      itera102_provider: "",
      itera102_model_id: "",
      itera102_language_code: "vi",
      itera102_speed: 1.0,
      itera102_stability: 0.5,
      itera102_similarity_boost: 0.75,
      itera102_style: 0.0,
      itera102_use_speaker_boost: true,
      edge_tts_voice: "vi-VN-HoaiMyNeural",
      edge_tts_speed: "1.0",
      itera102_api_key_configured: false,
      llm_api_key_configured: false,
    }),
  );

  const [voices, setVoices] = useState<VoiceItem[]>([]);
  const [lastCrawlStats, setLastCrawlStats] = useState<ProfileAiVideoResponse | null>(null);
  const [manifestLog, setManifestLog] = useState<ProfileAiVideoLogResponse | null>(null);

  useEffect(() => {
    async function bootstrap() {
      try {
        const [loadedSettings, loadedVoices] = await Promise.all([
          api.getSettings(),
          api.listVoices().catch(() => ({ voices: [] })),
        ]);
        setSettings(mapSettings(loadedSettings));
        setVoices(loadedVoices.voices || []);
        const savedVoice = loadFormMemory<{ voiceId: string }>(FORM_MEMORY_KEY).voiceId;
        if (savedVoice !== undefined && (savedVoice === "" || (loadedVoices.voices || []).some((v) => v.voice_id === savedVoice))) {
          setVoiceId(savedVoice);
        } else if (loadedSettings.itera102_voice_id && loadedSettings.itera102_voice_id.trim()) {
          setVoiceId("");
        } else if (loadedVoices.voices && loadedVoices.voices.length > 0) {
          const defaultVoice = loadedVoices.voices.find((v) => v.voice_id === "google-free") || loadedVoices.voices[0];
          setVoiceId(defaultVoice.voice_id);
        }
      } catch (err) {
        toast({
          title: "Không thể tải cấu hình",
          description: err instanceof Error ? err.message : "Lỗi kết nối",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    }
    bootstrap();
  }, []);

  async function loadManifestLog() {
    try {
      const data = await api.getProfileAiVideoLog();
      setManifestLog(data);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadManifestLog();
  }, []);

  const jobItems = snapshot?.items || [];
  const isJobRunning = snapshot?.status === "running";
  const isJobPaused = snapshot?.status === "paused";
  const canControl = isJobRunning || isJobPaused;

  async function handlePauseJob() {
    setControlling(true);
    try {
      await api.pauseJob();
      toast({
        title: "Đã yêu cầu tạm dừng job",
      });
    } catch (err) {
      toast({
        title: "Tạm dừng thất bại",
        description: err instanceof Error ? err.message : "Lỗi kết nối",
        variant: "destructive",
      });
    } finally {
      setControlling(false);
    }
  }

  async function handleResumeJob() {
    setControlling(true);
    try {
      await api.resumeJob();
      toast({
        title: "Đã tiếp tục job",
      });
    } catch (err) {
      toast({
        title: "Tiếp tục thất bại",
        description: err instanceof Error ? err.message : "Lỗi kết nối",
        variant: "destructive",
      });
    } finally {
      setControlling(false);
    }
  }

  async function handleCancelJob() {
    setControlling(true);
    try {
      await api.cancelJob();
      toast({
        title: "Đã yêu cầu hủy job",
      });
    } catch (err) {
      toast({
        title: "Hủy thất bại",
        description: err instanceof Error ? err.message : "Lỗi kết nối",
        variant: "destructive",
      });
    } finally {
      setControlling(false);
    }
  }

  const currentProgress = useMemo(() => {
    if (!jobItems.length) return 0;
    const total = jobItems.reduce((sum, item) => {
      if (item.status === "done" || item.status === "completed") return sum + 100;
      if (item.status === "failed" || item.status === "error") return sum + 100;
      if (item.status === "running") return sum + 50;
      return sum;
    }, 0);
    return Math.round(total / jobItems.length);
  }, [jobItems]);

  async function handlePickFolder() {
    try {
      const res = await api.pickFolder();
      if (res.path) {
        setSettings((prev) => ({ ...prev, finalOutputDir: res.path || "" }));
      }
    } catch (err) {
      toast({
        title: "Lỗi chọn thư mục",
        description: err instanceof Error ? err.message : "Thất bại",
        variant: "destructive",
      });
    }
  }

  async function handlePickFile(field: keyof typeof settings, title: string) {
    try {
      const res = await api.pickFile({ title });
      if (res.path) {
        setSettings((prev) => ({ ...prev, [field]: res.path || "" }));
      }
    } catch (err) {
      toast({
        title: "Lỗi chọn file",
        description: err instanceof Error ? err.message : "Thất bại",
        variant: "destructive",
      });
    }
  }

  async function handleSaveSettings() {
    setSettingsSaving(true);
    try {
      await api.saveSettings({
        final_output_dir: settings.finalOutputDir,
        custom_style1_logo_path: settings.style1LogoPath,
        custom_style1_card_bg_path: settings.style1CardBgPath,
        custom_style1_nhay_path: settings.style1NhayPath,
        custom_style1_black_bg_path: settings.style1BlackBgPath,
        custom_style2_logo_path: settings.style2LogoPath,
        custom_style2_card_bg_path: settings.style2CardBgPath,
        custom_style2_nhay_path: settings.style2NhayPath,
        custom_style2_black_bg_path: settings.style2BlackBgPath,
        custom_style3_logo_path: settings.style3LogoPath,
        custom_style3_card_bg_path: settings.style3CardBgPath,
        custom_style3_nhay_path: settings.style3NhayPath,
        custom_style3_black_bg_path: settings.style3BlackBgPath,
      });
      toast({
        title: "Đã lưu cài đặt",
        description: "Cấu hình render và tài nguyên đã được cập nhật.",
      });
    } catch (err) {
      toast({
        title: "Lưu cài đặt thất bại",
        description: err instanceof Error ? err.message : "Lỗi không xác định",
        variant: "destructive",
      });
    } finally {
      setSettingsSaving(false);
    }
  }

  function parseNumber(raw: string, fallback: number, min: number, max: number): number {
    const v = parseFloat(raw);
    return isNaN(v) ? fallback : Math.min(Math.max(v, min), max);
  }

  async function handleSubmit() {
    const rawUrl = profileUrl.trim();
    if (!rawUrl) {
      toast({
        title: "Thiếu link profile",
        description: "Vui lòng nhập link profile TikTok hoặc @username của kênh.",
        variant: "destructive",
      });
      return;
    }

    setSubmitting(true);
    try {
      const maxV = parseInt(maxVideos, 10);
      const res = await api.createProfileAiVideo({
        profile_url: rawUrl,
        video_shift_ratio: parseNumber(videoShiftRatio, 0.25, 0.0, 1.0),
        video_scale: parseNumber(videoScale, 1.08, 0.1, 3.0),
        style: selectedStyle,
        voice_id: voiceId || undefined,
        mode_pipeline: modePipeline,
        force_rerun_all: forceRerunAll,
        max_videos: maxV > 0 ? maxV : undefined,
        auto_showcase: autoShowcase,
        showcase_dry: showcaseDry,
        auto_post: autoPost,
        post_dry: postDry,
        post_delete_after: postDeleteAfter,
        script_theme: scriptTheme.trim() || undefined,
      });
      saveFormMemory<FormMemory>(FORM_MEMORY_KEY, {
        profileUrl: rawUrl,
        videoShiftRatio,
        videoScale,
        selectedStyle,
        voiceId,
        maxVideos,
        autoShowcase,
        showcaseDry,
        autoPost,
        postDry,
        postDeleteAfter,
        scriptTheme,
      });

      setLastCrawlStats(res);
      await loadManifestLog();

      if (res.status === "skipped_all") {
        toast({
          title: "Đã hoàn thành trước đó",
          description: res.message,
        });
      } else {
        toast({
          title: "Bắt đầu gen video",
          description: res.message,
        });
      }
    } catch (err) {
      toast({
        title: "Khởi động job thất bại",
        description: err instanceof ApiError ? err.message : "Không thể bắt đầu job",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function openOutputFolder() {
    try {
      await api.openFolder(settings.finalOutputDir);
    } catch (err) {
      toast({
        title: "Lỗi mở thư mục",
        description: err instanceof Error ? err.message : "Thất bại",
        variant: "destructive",
      });
    }
  }

  async function revealPath(path?: string | null) {
    if (!path) return;
    try {
      await api.revealFile(path);
    } catch (err) {
      toast({
        title: "Lỗi mở file",
        description: err instanceof Error ? err.message : "Thất bại",
        variant: "destructive",
      });
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-6 py-10">
        <div className="flex items-center gap-3 text-slate-300">
          <LoaderCircle className="h-6 w-6 animate-spin text-violet-400" />
          <span>Đang tải cấu hình Profile AI Video...</span>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen py-6 sm:py-8 lg:py-10">
      <div className="app-shell flex flex-col gap-6 lg:gap-8">
        {/* Navigation & Header */}
        <header className="glass-panel flex flex-col gap-5 rounded-[2rem] px-5 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between border-violet-500/30 bg-gradient-to-r from-violet-950/40 via-purple-950/20 to-slate-900/40">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-violet-500/20 px-2.5 py-0.5 text-xs font-semibold text-violet-300 border border-violet-500/30">
                Chuyên sâu Profile
              </span>
              <h1 className="text-xl font-bold tracking-tight text-white sm:text-2xl">
                Crawl Profile & Gen Video AI
              </h1>
            </div>
            <p className="text-xs text-slate-300">
              Nhập link TikTok profile → Tự động cào danh sách video → Bỏ qua link đã hoàn thành (JSON manifest) → Gen video chuẩn tỷ lệ kéo 0.25.
            </p>
          </div>

          <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-black/30 p-1.5 backdrop-blur-md">
            <Link href="/" className="rounded-xl px-3 py-2 text-xs font-medium text-slate-300 hover:text-white transition-colors">
              Nhập thủ công
            </Link>
            <Link href="/ai-video" className="rounded-xl px-3 py-2 text-xs font-medium text-slate-300 hover:text-white transition-colors">
              Gen video AI
            </Link>
            <Link href="/profile-ai-video" className="rounded-xl bg-violet-600 px-3.5 py-2 text-xs font-semibold text-white shadow-lg shadow-violet-600/30">
              Profile AI Video
            </Link>
            <Link href="/montage" className="rounded-xl px-3 py-2 text-xs font-medium text-slate-300 hover:text-white transition-colors">
              Xào TikTok
            </Link>
            <Link href="/test-render" className="rounded-xl px-3 py-2 text-xs font-medium text-slate-300 hover:text-white transition-colors">
              Test Render
            </Link>
          </nav>
        </header>

        {/* Layout Grid */}
        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)]">
          {/* Left: Collapsible Settings Sidebar */}
          <aside className="space-y-5 xl:sticky xl:top-5 xl:self-start">
            <Card className="overflow-hidden bg-white/[0.045] border-white/10">
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between gap-3">
                  <CardTitle className="text-sm font-semibold text-white">
                    Cấu hình Output & Style
                  </CardTitle>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 px-2 text-xs text-slate-400 hover:text-white"
                    onClick={() => setSettingsExpanded((v) => !v)}
                  >
                    {settingsExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </Button>
                </div>
              </CardHeader>
              {settingsExpanded ? (
                <CardContent className="space-y-4 pt-0">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">Thư mục Video Xuất</label>
                    <div className="flex gap-2">
                      <Input
                        value={settings.finalOutputDir}
                        onChange={(event) =>
                          setSettings((prev) => ({
                            ...prev,
                            finalOutputDir: event.target.value,
                          }))
                        }
                        placeholder="Thư mục xuất video..."
                        className="bg-black/30 text-xs border-white/10"
                      />
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        className="shrink-0 bg-white/10 hover:bg-white/20 text-white"
                        onClick={handlePickFolder}
                      >
                        <Folder className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  {/* Style Assets Tabs */}
                  <div className="space-y-2 pt-2 border-t border-white/10">
                    <label className="text-xs font-medium text-slate-300">Tùy biến Background / Overlay</label>
                    <div className="grid grid-cols-3 gap-1 rounded-xl bg-black/40 p-1 border border-white/10">
                      {(["style1", "style2", "style3"] as const).map((st) => (
                        <button
                          key={st}
                          type="button"
                          onClick={() => setSettingsStyleTab(st)}
                          className={`rounded-lg py-1 text-[11px] font-medium transition-all ${
                            settingsStyleTab === st
                              ? "bg-violet-600 text-white shadow-sm"
                              : "text-slate-400 hover:text-white"
                          }`}
                        >
                          {st.toUpperCase()}
                        </button>
                      ))}
                    </div>

                    {settingsStyleTab === "style1" ? (
                      <div className="space-y-2 pt-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Card BG:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style1CardBgPath", "Chọn Card BG Style 1")}>Chọn ảnh</Button>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Logo:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style1LogoPath", "Chọn Logo Style 1")}>Chọn logo</Button>
                        </div>
                      </div>
                    ) : settingsStyleTab === "style2" ? (
                      <div className="space-y-2 pt-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Background:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style2CardBgPath", "Chọn BG Style 2")}>Chọn ảnh</Button>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Logo:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style2LogoPath", "Chọn Logo Style 2")}>Chọn logo</Button>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-2 pt-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Background:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style3CardBgPath", "Chọn BG Style 3")}>Chọn ảnh</Button>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Logo:</span>
                          <Button variant="ghost" size="sm" className="h-6 text-[11px] text-violet-400" onClick={() => handlePickFile("style3LogoPath", "Chọn Logo Style 3")}>Chọn logo</Button>
                        </div>
                      </div>
                    )}
                  </div>

                  <Button
                    className="w-full bg-violet-600 hover:bg-violet-500 text-white text-xs mt-2"
                    size="sm"
                    disabled={settingsSaving}
                    onClick={handleSaveSettings}
                  >
                    {settingsSaving ? "Đang lưu..." : "Lưu cài đặt"}
                  </Button>
                </CardContent>
              ) : null}
            </Card>

            {/* Quick Info & Manifest Summary */}
            <Card className="overflow-hidden bg-violet-500/[0.05] border-violet-500/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs font-semibold text-violet-300 flex items-center gap-1.5">
                  <Globe className="h-4 w-4" /> Manifest Log JSON
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-slate-300 pt-1">
                <p className="text-[11px] text-slate-400">
                  File log tự động được ghi tại thư mục output để chống trùng lặp.
                </p>
                <div className="flex justify-between border-t border-white/5 pt-2 text-[11px]">
                  <span className="text-slate-400">Tổng video đã log:</span>
                  <span className="font-semibold text-white">{manifestLog?.total_logged || 0}</span>
                </div>
                <div className="flex justify-between text-[11px]">
                  <span className="text-slate-400">Tỷ lệ kéo mặc định:</span>
                  <span className="font-mono font-semibold text-emerald-400">0.25</span>
                </div>
              </CardContent>
            </Card>
          </aside>

          {/* Right: Main Content Panel */}
          <section className="space-y-6">
            {/* Input Card */}
            <Card className="overflow-hidden border-violet-500/40 bg-gradient-to-b from-violet-500/[0.08] to-white/[0.02]">
              <CardHeader className="pb-4">
                <div className="flex flex-col gap-1">
                  <CardTitle className="text-lg font-bold text-white flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-violet-400" />
                    Cào & Chạy Video theo Kênh TikTok
                  </CardTitle>
                  <p className="text-xs text-slate-400">
                    Dán link profile (ví dụ: <code className="text-violet-300">https://www.tiktok.com/@username</code> hoặc <code className="text-violet-300">@username</code>)
                  </p>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Profile Link Input */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-slate-200">
                    Link TikTok Profile / Username
                  </label>
                  <Input
                    value={profileUrl}
                    onChange={(e) => setProfileUrl(e.target.value)}
                    placeholder="https://www.tiktok.com/@username hoặc @username"
                    className="border-white/10 bg-black/40 text-sm placeholder:text-slate-500 focus:border-violet-500"
                    disabled={submitting || isJobRunning}
                  />
                </div>

                {/* Param Controls: Ratio 0.25 default, Scale 1.08, Voice, Style */}
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">
                      Tỷ lệ kéo video (video_shift_ratio)
                    </label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0.0"
                      max="1.0"
                      value={videoShiftRatio}
                      onChange={(e) => setVideoShiftRatio(e.target.value)}
                      className="bg-black/30 border-white/10 text-xs font-mono"
                      disabled={submitting || isJobRunning}
                    />
                    <p className="text-[10px] text-slate-400">Mặc định: 0.25</p>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">
                      Scale Zoom video (video_scale)
                    </label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0.1"
                      max="3.0"
                      value={videoScale}
                      onChange={(e) => setVideoScale(e.target.value)}
                      className="bg-black/30 border-white/10 text-xs font-mono"
                      disabled={submitting || isJobRunning}
                    />
                    <p className="text-[10px] text-slate-400">Mặc định: 1.08</p>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">Giọng đọc TTS</label>
                    <Select value={voiceId} onValueChange={setVoiceId} disabled={submitting || isJobRunning}>
                      <SelectTrigger className="bg-black/30 border-white/10 text-xs">
                        <SelectValue placeholder="Chọn giọng đọc" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="" className="text-xs">
                          Default (ITERA102 từ .env)
                        </SelectItem>
                        {voices.map((v) => (
                          <SelectItem key={v.voice_id} value={v.voice_id} className="text-xs">
                            {v.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">Style Layout</label>
                    <Select
                      value={selectedStyle}
                      onValueChange={(v) => setSelectedStyle(v as "style1" | "style2" | "style3")}
                      disabled={submitting || isJobRunning}
                    >
                      <SelectTrigger className="bg-black/30 border-white/10 text-xs">
                        <SelectValue placeholder="Chọn style" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="style1" className="text-xs">Style 1 - Review Tiệm</SelectItem>
                        <SelectItem value="style2" className="text-xs">Style 2 - Tạp Hóa Xanh</SelectItem>
                        <SelectItem value="style3" className="text-xs">Style 3 - Layout 3</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-medium text-slate-300">
                      Số video cần chạy
                    </label>
                    <Input
                      type="number"
                      min="0"
                      max="500"
                      value={maxVideos}
                      onChange={(e) => setMaxVideos(e.target.value)}
                      className="bg-black/30 border-white/10 text-xs font-mono"
                      placeholder="0 = không giới hạn"
                      disabled={submitting || isJobRunning}
                    />
                    <p className="text-[10px] text-slate-400">0 = lấy tất cả video hợp lệ</p>
                  </div>
                </div>

                <ScriptThemeInput
                  id="profile-script-theme"
                  value={scriptTheme}
                  onChange={setScriptTheme}
                  disabled={submitting || isJobRunning}
                />

                <ShowcaseOptions
                  enabled={autoShowcase}
                  dry={showcaseDry}
                  onEnabledChange={setAutoShowcase}
                  onDryChange={setShowcaseDry}
                  disabled={submitting || isJobRunning}
                />
                <PostOptions
                  enabled={autoPost}
                  dry={postDry}
                  deleteAfter={postDeleteAfter}
                  onDeleteAfterChange={setPostDeleteAfter}
                  onEnabledChange={setAutoPost}
                  onDryChange={setPostDry}
                  disabled={submitting || isJobRunning}
                  refreshKey={isJobRunning}
                />

                {/* Pipeline Mode & Options */}
                <div className="flex flex-wrap items-center justify-between gap-4 pt-1 border-t border-white/5 text-xs">
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
                      <input
                        type="checkbox"
                        checked={forceRerunAll}
                        onChange={(e) => setForceRerunAll(e.target.checked)}
                        className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
                        disabled={submitting || isJobRunning}
                      />
                      <span>Chạy lại tất cả (bỏ qua lọc đã done)</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
                      <input
                        type="checkbox"
                        checked={modePipeline === "mock"}
                        onChange={(e) => setModePipeline(e.target.checked ? "mock" : "live")}
                        className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
                        disabled={submitting || isJobRunning}
                      />
                      <span>Chế độ Mock (test nhanh giao diện)</span>
                    </label>
                  </div>

                  <Button
                    size="default"
                    className="bg-violet-600 hover:bg-violet-500 text-white font-semibold shadow-lg shadow-violet-600/30 px-6 gap-2"
                    disabled={submitting || isJobRunning || !profileUrl.trim()}
                    onClick={handleSubmit}
                  >
                    {submitting ? (
                      <>
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                        Đang cào & phân tích...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4 fill-current" />
                        Bắt đầu Crawl & Gen Video
                      </>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Status & Realtime Progress */}
            {lastCrawlStats ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <Card className="bg-white/[0.03] border-white/10 p-4">
                  <p className="text-xs text-slate-400">Đã cào được</p>
                  <p className="text-2xl font-bold text-white mt-1">{lastCrawlStats.crawled_count} <span className="text-xs font-normal text-slate-400">videos</span></p>
                </Card>
                <Card className="bg-white/[0.03] border-white/10 p-4">
                  <p className="text-xs text-slate-400">Bỏ qua (đã Done)</p>
                  <p className="text-2xl font-bold text-amber-400 mt-1">{lastCrawlStats.skipped_count} <span className="text-xs font-normal text-slate-400">videos</span></p>
                </Card>
                <Card className="bg-white/[0.03] border-white/10 p-4">
                  <p className="text-xs text-slate-400">Đang thực thi</p>
                  <p className="text-2xl font-bold text-emerald-400 mt-1">{lastCrawlStats.queued_count} <span className="text-xs font-normal text-slate-400">videos</span></p>
                </Card>
              </div>
            ) : null}

            {/* Job Execution Table */}
            <Card className="overflow-hidden bg-white/[0.045] border-white/10">
              <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between pb-4">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-base font-bold text-white">
                      Tiến độ Xử lý Hàng loạt
                    </CardTitle>
                    <Badge variant={statusVariant(snapshot?.status)} className="text-[11px]">
                      {statusLabel(snapshot?.status)}
                    </Badge>
                    <Badge
                      variant={
                        socketStatus === "open"
                          ? "success"
                          : socketStatus === "connecting"
                            ? "warning"
                            : socketStatus === "closed"
                              ? "destructive"
                              : "secondary"
                      }
                      className="text-[11px]"
                    >
                      Socket: {socketStatus === "open"
                        ? "Đã kết nối"
                        : socketStatus === "connecting"
                          ? "Đang kết nối"
                          : socketStatus === "closed"
                            ? "Đã đóng"
                            : "Chưa bật"}
                    </Badge>
                  </div>
                  <p className="text-xs text-slate-400">
                    Realtime theo dõi tiến trình tải video, gen kịch bản, đọc TTS và render thành phẩm.
                  </p>
                  {socketError ? (
                    <p className="text-xs font-medium text-rose-300" role="alert">
                      Lỗi realtime: {socketError}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {canControl ? (
                    <>
                      {isJobPaused ? (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={controlling}
                          className="border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs gap-1.5"
                          onClick={handleResumeJob}
                        >
                          <Play className="h-3.5 w-3.5 fill-current" /> Tiếp tục
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={controlling}
                          className="border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-xs gap-1.5"
                          onClick={handlePauseJob}
                        >
                          <Pause className="h-3.5 w-3.5" /> Tạm dừng
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlling}
                        className="border-rose-500/40 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 text-xs gap-1.5"
                        onClick={handleCancelJob}
                      >
                        <Square className="h-3.5 w-3.5 fill-current" /> Dừng hẳn
                      </Button>
                    </>
                  ) : null}
                  <Button
                    variant="outline"
                    size="sm"
                    className="border-white/10 bg-white/5 hover:bg-white/10 text-white text-xs gap-1.5"
                    onClick={openOutputFolder}
                  >
                    <FolderOpen className="h-4 w-4" /> Mở thư mục kết quả
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Progress bar */}
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs text-slate-400">
                    <span>Tổng tiến độ</span>
                    <span className="font-semibold text-white">{currentProgress}%</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all duration-300"
                      style={{ width: `${currentProgress}%` }}
                    />
                  </div>
                </div>

                {/* Table */}
                <div className="overflow-hidden rounded-xl border border-white/10">
                  <div className="max-h-96 overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-white/10 text-left text-xs font-semibold uppercase tracking-wider text-slate-400 bg-white/[0.02]">
                          <th className="px-4 py-3">#</th>
                          <th className="px-4 py-3">URL / Sản phẩm</th>
                          <th className="px-4 py-3">Trạng thái</th>
                          <th className="px-4 py-3 text-right">Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobItems.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-4 py-8 text-center text-xs text-slate-500">
                              Chưa có video nào trong hàng đợi. Nhập link profile ở trên để bắt đầu.
                            </td>
                          </tr>
                        ) : (
                          jobItems.map((item) => {
                            const titleHint = (item.script as { product_name?: string } | undefined)?.product_name || item.product_name_hint;
                            return (
                              <tr key={item.index} className="border-b border-white/5 text-white hover:bg-white/[0.02] transition-colors">
                                <td className="px-4 py-3 font-mono text-xs text-slate-400">
                                  {item.index}
                                </td>
                                <td className="px-4 py-3">
                                  <div className="max-w-md truncate text-xs font-medium text-slate-200" title={item.url}>
                                    {item.url}
                                  </div>
                                  {titleHint ? (
                                    <div className="text-[11px] text-violet-300 font-medium truncate mt-0.5">
                                      {titleHint}
                                    </div>
                                  ) : null}
                                  {item.error ? (
                                    <div className="mt-1 text-[11px] text-rose-400 flex items-center gap-1">
                                      <AlertCircle className="h-3 w-3 shrink-0" />
                                      <span className="truncate">{item.error}</span>
                                    </div>
                                  ) : null}
                                </td>
                                <td className="px-4 py-3">
                                  <Badge variant={statusVariant(item.status)} className="text-[11px]">
                                    {statusLabel(item.status)}
                                  </Badge>
                                  <ShowcaseBadge showcase={item.showcase} />
                                  <PostBadge post={item.post} />
                                </td>
                                <td className="px-4 py-3 text-right">
                                  {item.final_video_path ? (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
                                      onClick={() => revealPath(item.final_video_path)}
                                    >
                                      Xem file
                                    </Button>
                                  ) : null}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>
        </div>
      </div>
    </main>
  );
}
