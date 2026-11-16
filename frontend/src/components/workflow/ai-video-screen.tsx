"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity, ChevronDown, Download, FolderOpen, Home,
  ListVideo, LoaderCircle, Play, Plus, Save, Sparkles, Trash2,
  Wand2, ZoomIn, MoveVertical, RefreshCw, CheckCircle2, AlertCircle, Copy
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PostBadge, PostOptions, ShowcaseBadge, ShowcaseOptions } from "@/components/workflow/showcase-controls";
import { useJobEvents } from "@/hooks/use-job-events";
import { loadFormMemory, saveFormMemory } from "@/lib/form-memory";
import { ScriptThemeInput } from "@/components/workflow/script-theme-input";
import { toast } from "@/hooks/use-toast";
import { api, ApiError, type SettingsResponse, type VoiceItem } from "@/lib/api";

function mapSettings(data: SettingsResponse) {
  return {
    finalOutputDir: data.final_output_dir || '',
    itera102VoiceId: data.itera102_voice_id || '',
    customStyle1LogoPath: data.custom_style1_logo_path || data.custom_logo_path || '',
    customStyle1CardBgPath: data.custom_style1_card_bg_path || data.custom_card_bg_path || '',
    customStyle1NhayPath: data.custom_style1_nhay_path || data.custom_nhay_path || '',
    customStyle2LogoPath: data.custom_style2_logo_path || '',
    customStyle2CardBgPath: data.custom_style2_card_bg_path || '',
    customStyle2NhayPath: data.custom_style2_nhay_path || '',
    customStyle3LogoPath: data.custom_style3_logo_path || '',
    customStyle3CardBgPath: data.custom_style3_card_bg_path || '',
    customStyle3NhayPath: data.custom_style3_nhay_path || '',
  };
}

function statusLabel(status?: string | null) {
  if (!status) return "Chờ xử lý";
  if (["done", "completed", "success"].includes(status)) return "Hoàn tất";
  if (["failed", "error"].includes(status)) return "Lỗi";
  if (status === "downloading") return "Đang tải TikTok";
  if (status === "scripting") return "AI nhận diện & viết kịch bản";
  if (status === "tts") return "Tạo giọng đọc TTS (ElevenLabs Tags)";
  if (status === "merging") return "Render & ghép layout 9:16";
  if (["processing", "running"].includes(status)) return "Đang chạy";
  return "Đang chờ";
}

function statusVariant(status?: string | null): "success" | "warning" | "secondary" | "destructive" {
  if (!status) return "secondary";
  if (["done", "completed", "success"].includes(status)) return "success";
  if (["failed", "error"].includes(status)) return "destructive";
  if (["processing", "running", "downloading", "scripting", "tts", "merging"].includes(status)) return "warning";
  return "secondary";
}

const FORM_MEMORY_KEY = "ai-video";

export function AiVideoScreen() {
  const [urlsText, setUrlsText] = useState("");
  const [videoShiftRatio, setVideoShiftRatio] = useState("0.3333");
  const [videoScale, setVideoScale] = useState("1.08");
  const [voiceId, setVoiceId] = useState("google-free");
  const [selectedStyle, setSelectedStyle] = useState<"style1" | "style2" | "style3">("style1");
  const [autoShowcase, setAutoShowcase] = useState(false);
  const [showcaseDry, setShowcaseDry] = useState(false);
  const [autoPost, setAutoPost] = useState(false);
  const [postDry, setPostDry] = useState(false);
  const [postDeleteAfter, setPostDeleteAfter] = useState(false);
  const [scriptTheme, setScriptTheme] = useState(""); // Chủ đề kịch bản AI, rỗng = AI tự chọn

  const [voices, setVoices] = useState<VoiceItem[]>([]);
  const [settings, setSettings] = useState({
    finalOutputDir: "",
    itera102VoiceId: "",
    customStyle1LogoPath: "",
    customStyle1CardBgPath: "",
    customStyle1NhayPath: "",
    customStyle2LogoPath: "",
    customStyle2CardBgPath: "",
    customStyle2NhayPath: "",
    customStyle3LogoPath: "",
    customStyle3CardBgPath: "",
    customStyle3NhayPath: "",
  });
  const [settingsStyleTab, setSettingsStyleTab] = useState<"style1" | "style2" | "style3">("style1");
  const [loading, setLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(false);

  const { snapshot, status: streamStatus, error: streamError } = useJobEvents(true);

  // Thông số lần chạy gần nhất (không giữ danh sách link vì đổi theo từng lần)
  type FormMemory = {
    videoShiftRatio: string;
    videoScale: string;
    voiceId: string;
    selectedStyle: "style1" | "style2" | "style3";
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
    if (m.videoShiftRatio !== undefined) setVideoShiftRatio(m.videoShiftRatio);
    if (m.videoScale !== undefined) setVideoScale(m.videoScale);
    if (m.selectedStyle) setSelectedStyle(m.selectedStyle);
    if (m.autoShowcase !== undefined) setAutoShowcase(m.autoShowcase);
    if (m.showcaseDry !== undefined) setShowcaseDry(m.showcaseDry);
    if (m.autoPost !== undefined) setAutoPost(m.autoPost);
    if (m.postDry !== undefined) setPostDry(m.postDry);
    if (m.postDeleteAfter !== undefined) setPostDeleteAfter(m.postDeleteAfter);
    // voiceId áp sau khi tải danh sách voice (bootstrap) để không bị ghi đè
  }, []);

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [settingsData, voicesResponse, serverDefaults] = await Promise.all([
          api.getSettings(),
          api.listVoices(),
          api.getAiVideoDefaults().catch(() => null),
        ]);
        if (!active) return;
        setSettings(mapSettings(settingsData));
        setVoices(voicesResponse.voices);
        if (voicesResponse.voices && voicesResponse.voices.length > 0) {
          const defaultVoice = voicesResponse.voices.find((v) => v.voice_id === "google-free") || voicesResponse.voices[0];
          setVoiceId(defaultVoice.voice_id);
        }
        // Setting ở backend là nguồn chính (bot Telegram cũng sửa được), ưu tiên hơn localStorage
        if (serverDefaults?.saved) {
          setVideoShiftRatio(String(serverDefaults.video_shift_ratio));
          setVideoScale(String(serverDefaults.video_scale));
          setSelectedStyle(serverDefaults.style);
          setAutoShowcase(serverDefaults.auto_showcase);
          setShowcaseDry(serverDefaults.showcase_dry);
          setAutoPost(serverDefaults.auto_post);
          setPostDry(serverDefaults.post_dry);
          setPostDeleteAfter(serverDefaults.post_delete_after);
          setScriptTheme(serverDefaults.script_theme);
        }
        const savedVoice = serverDefaults?.saved
          ? serverDefaults.voice_id
          : loadFormMemory<FormMemory>(FORM_MEMORY_KEY).voiceId;
        if (savedVoice && (savedVoice === "default" || (voicesResponse.voices || []).some((v) => v.voice_id === savedVoice))) {
          setVoiceId(savedVoice);
        }
      } catch (error) {
        toast({
          variant: "destructive",
          title: "Không tải được dữ liệu",
          description: error instanceof ApiError ? error.message : "Lỗi khởi tạo",
        });
      } finally {
        if (active) setLoading(false);
      }
    }
    bootstrap();
    return () => { active = false; };
  }, []);

  // Form đổi là ghi nhớ ngay (localStorage) + đồng bộ backend để bot Telegram
  // chạy đúng setting đang chọn. Đợi tải xong để không ghi đè bằng giá trị mặc định.
  useEffect(() => {
    if (loading) return;
    const timer = window.setTimeout(() => {
      saveFormMemory<FormMemory>(FORM_MEMORY_KEY, {
        videoShiftRatio, videoScale, voiceId, selectedStyle,
        autoShowcase, showcaseDry, autoPost, postDry, postDeleteAfter, scriptTheme,
      });
      api.saveAiVideoDefaults({
        video_shift_ratio: parseNumber(videoShiftRatio, 0.3333, 0.0, 1.0),
        video_scale: parseNumber(videoScale, 1.08, 0.1, 3.0),
        voice_id: voiceId,
        style: selectedStyle,
        auto_showcase: autoShowcase,
        showcase_dry: showcaseDry,
        auto_post: autoPost,
        post_dry: postDry,
        post_delete_after: postDeleteAfter,
        script_theme: scriptTheme.trim(),
      }).catch(() => {
        // backend tắt/lỗi: bot dùng setting lưu lần trước, không cần báo
      });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [loading, videoShiftRatio, videoScale, voiceId, selectedStyle, autoShowcase, showcaseDry, autoPost, postDry, postDeleteAfter, scriptTheme]);

  useEffect(() => {
    if (streamError) toast({ variant: "warning", title: "Realtime gián đoạn", description: streamError });
  }, [streamError]);

  const job = snapshot ?? null;
  const jobItems = job?.items ?? [];

  const currentProgress = (() => {
    if (!jobItems.length) return 0;
    const total = jobItems.reduce((sum, item) => {
      if (["done", "completed", "success", "failed", "error"].includes(item.status)) return sum + 100;
      if (item.status === "merging") return sum + 85;
      if (item.status === "tts") return sum + 65;
      if (item.status === "scripting") return sum + 40;
      if (item.status === "downloading") return sum + 20;
      return sum;
    }, 0);
    return Math.round(total / jobItems.length);
  })();

  async function handlePickFolder() {
    try {
      const response = await api.pickFolder();
      if (response.path) setSettings((current) => ({ ...current, finalOutputDir: response.path ?? current.finalOutputDir }));
    } catch (error) {
      toast({ variant: "destructive", title: "Không chọn được thư mục", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    }
  }

  async function handlePickFile(field: keyof typeof settings, title: string) {
    try {
      const response = await api.pickFile({ title });
      if (response.path) {
        setSettings((current) => ({ ...current, [field]: response.path ?? current[field] }));
      }
    } catch (error) {
      toast({ variant: "destructive", title: "Không chọn được file", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    }
  }

  async function handleSaveSettings() {
    setSavingSettings(true);
    try {
      await api.saveSettings({
        final_output_dir: settings.finalOutputDir,
        itera102_voice_id: settings.itera102VoiceId,
        custom_style1_logo_path: settings.customStyle1LogoPath,
        custom_style1_card_bg_path: settings.customStyle1CardBgPath,
        custom_style1_nhay_path: settings.customStyle1NhayPath,
        custom_style2_logo_path: settings.customStyle2LogoPath,
        custom_style2_card_bg_path: settings.customStyle2CardBgPath,
        custom_style2_nhay_path: settings.customStyle2NhayPath,
        custom_style3_logo_path: settings.customStyle3LogoPath,
        custom_style3_card_bg_path: settings.customStyle3CardBgPath,
        custom_style3_nhay_path: settings.customStyle3NhayPath,
      });
      toast({ variant: "success", title: "Đã lưu settings" });
    } catch (error) {
      toast({ variant: "destructive", title: "Lưu settings thất bại", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    } finally {
      setSavingSettings(false);
    }
  }

  function parseNumber(raw: string, fallback: number, min: number, max: number): number {
    const v = parseFloat(raw);
    return isFinite(v) && v >= min && v <= max ? v : fallback;
  }

  async function handleSubmit() {
    const urls = urlsText
      .split(/\r?\n/)
      .map((u) => u.trim())
      .filter((u) => u.length > 0 && !u.startsWith("#"));

    if (!urls.length) {
      toast({ variant: "warning", title: "Thiếu link TikTok", description: "Vui lòng nhập ít nhất 1 link TikTok." });
      return;
    }

    const shiftRatio = parseNumber(videoShiftRatio, 0.3333, 0.0, 1.0);
    const scale = parseNumber(videoScale, 1.08, 0.1, 3.0);
    const chosenVoiceId = voiceId === "default" ? undefined : voiceId;

    const items = urls.map((u) => ({
      url: u,
      video_shift_ratio: shiftRatio,
      video_scale: scale,
      voice_id: chosenVoiceId,
      style: selectedStyle,
    }));

    setSubmitting(true);
    try {
      await api.createBatch({
        items,
        default_voice_id: chosenVoiceId,
        default_style: selectedStyle,
        auto_showcase: autoShowcase,
        showcase_dry: showcaseDry,
        auto_post: autoPost,
        post_dry: postDry,
        post_delete_after: postDeleteAfter,
        script_theme: scriptTheme.trim() || undefined,
      });
      saveFormMemory<FormMemory>(FORM_MEMORY_KEY, {
        videoShiftRatio,
        videoScale,
        voiceId,
        selectedStyle,
        autoShowcase,
        showcaseDry,
        autoPost,
        postDry,
        postDeleteAfter,
        scriptTheme,
      });
      toast({
        variant: "success",
        title: `Đã khởi tạo quy trình AI Video (${items.length} link)`,
        description: "Hệ thống đang tự động tải, gọi AI phân tích sản phẩm và tạo video.",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Khởi tạo thất bại",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function openOutputFolder() {
    if (!settings.finalOutputDir) {
      toast({ variant: "warning", title: "Chưa cấu hình thư mục output" });
      return;
    }
    try {
      await api.openFolder(settings.finalOutputDir);
    } catch (error) {
      toast({ variant: "destructive", title: "Không mở được thư mục", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    }
  }

  async function revealPath(path?: string | null) {
    if (!path) return;
    try {
      await api.revealFile(path);
    } catch (error) {
      toast({ variant: "destructive", title: "Không mở được file", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-6 py-10">
        <div className="glass-panel flex items-center gap-3 rounded-2xl px-5 py-4 text-sm text-slate-200">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải cấu hình...
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen py-6 sm:py-8 lg:py-10">
      <div className="app-shell flex flex-col gap-6 lg:gap-8">
        {/* Header */}
        <header className="glass-panel flex flex-col gap-5 rounded-[2rem] px-5 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between border-violet-500/30 bg-gradient-to-r from-violet-950/40 via-purple-950/20 to-slate-900/40">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-2xl border border-violet-400/40 bg-violet-500/20 text-violet-300 shadow-[0_0_20px_rgba(139,92,246,0.3)]">
              <Sparkles className="size-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-white">AI TikTok Link-to-Video</h1>
                <Badge className="bg-violet-600/80 hover:bg-violet-600 text-white text-xs border-none">9Router AI</Badge>
              </div>
              <p className="text-sm text-slate-300">
                Chỉ cần dán link TikTok: AI tự động phân tích sản phẩm, gắn cảm xúc ElevenLabs v3, lồng tiếng TTS và đặt tên video chuẩn <strong className="text-violet-300">[Caption] [Hashtags].mp4</strong>
              </p>
            </div>
          </div>
          <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-black/30 p-1.5 backdrop-blur-md">
            <Badge variant={streamStatus === "open" ? "success" : streamStatus === "connecting" ? "warning" : "secondary"}>
              WS {streamStatus}
            </Badge>
            <Button asChild variant="ghost"><Link href="/"><Home className="size-4" /> Home</Link></Button>
            <Button asChild variant="ghost"><Link href="/profile-ai-video"><Sparkles className="size-4 text-violet-400" /> Profile AI Video</Link></Button>
            <Button asChild variant="ghost"><Link href="/auto-gen-video"><Wand2 className="size-4" /> Auto Gen</Link></Button>
            <Button asChild variant="ghost"><Link href="/review"><ListVideo className="size-4" /> Review</Link></Button>
            <Button asChild variant="ghost"><Link href="/montage"><Sparkles className="size-4" /> Xào video</Link></Button>
          </nav>
        </header>

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)]">
          {/* Settings sidebar */}
          <aside className="space-y-5 xl:sticky xl:top-5 xl:self-start">
            <Card className="overflow-hidden bg-white/[0.045] border-white/10">
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-white text-base">Thư mục đầu ra</CardTitle>
                    <CardDescription className="truncate text-xs">{settings.finalOutputDir || "Chưa chọn output"}</CardDescription>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setSettingsExpanded((current) => !current)}
                    aria-expanded={settingsExpanded}
                  >
                    <ChevronDown className={`size-4 transition-transform ${settingsExpanded ? "rotate-180" : ""}`} />
                  </Button>
                </div>
              </CardHeader>
              {settingsExpanded ? (
                <CardContent className="space-y-4 pt-0">
                  <div className="space-y-2">
                    <Label htmlFor="output-dir" className="text-xs font-semibold text-slate-300">Đường dẫn folder output</Label>
                    <div className="flex gap-2">
                      <Input id="output-dir" className="text-xs" value={settings.finalOutputDir} onChange={(e) => setSettings((current) => ({ ...current, finalOutputDir: e.target.value }))} />
                      <Button size="icon" variant="outline" title="Chọn thư mục" onClick={handlePickFolder}><FolderOpen className="size-4" /></Button>
                    </div>
                  </div>

                  <div className="border-t border-white/10 pt-3 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-violet-300">Tùy chỉnh ảnh layout</div>
                      <div className="flex rounded-lg border border-white/10 bg-black/40 p-0.5 text-[11px]">
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style1")}
                          className={`rounded px-2 py-0.5 font-medium transition ${
                            settingsStyleTab === "style1" ? "bg-violet-600 text-white" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 1 (Đỏ)
                        </button>
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style2")}
                          className={`rounded px-2 py-0.5 font-medium transition ${
                            settingsStyleTab === "style2" ? "bg-emerald-600 text-white" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 2 (Xanh)
                        </button>
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style3")}
                          className={`rounded px-2 py-0.5 font-medium transition ${
                            settingsStyleTab === "style3" ? "bg-pink-600 text-white" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 3 (Hồng)
                        </button>
                      </div>
                    </div>

                    {settingsStyleTab === "style1" ? (
                      <div className="space-y-3 rounded-xl border border-red-500/20 bg-red-500/[0.03] p-2.5">
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style1-logo" className="text-[11px] text-slate-300">Logo (Style 1)</Label>
                            {settings.customStyle1LogoPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1LogoPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style1-logo" placeholder="Mặc định public/logo_tiembachhoa.png" className="text-xs h-8" value={settings.customStyle1LogoPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle1LogoPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1LogoPath", "Chọn logo Style 1")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style1-card-bg" className="text-[11px] text-slate-300">Background Card (Style 1)</Label>
                            {settings.customStyle1CardBgPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1CardBgPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style1-card-bg" placeholder="Mặc định public/red-bg.png" className="text-xs h-8" value={settings.customStyle1CardBgPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle1CardBgPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1CardBgPath", "Chọn Background Card Style 1")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style1-nhay" className="text-[11px] text-slate-300">Icon Nháy (Style 1)</Label>
                            {settings.customStyle1NhayPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1NhayPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style1-nhay" placeholder="Mặc định public/nhay.png" className="text-xs h-8" value={settings.customStyle1NhayPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle1NhayPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1NhayPath", "Chọn icon nháy Style 1")}>Chọn</Button>
                          </div>
                        </div>
                      </div>
                    ) : settingsStyleTab === "style2" ? (
                      <div className="space-y-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] p-2.5">
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style2-logo" className="text-[11px] text-slate-300">Logo (Style 2)</Label>
                            {settings.customStyle2LogoPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle2LogoPath: ''}))} className="text-[10px] text-emerald-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style2-logo" placeholder="Mặc định public/style2/logo.png" className="text-xs h-8" value={settings.customStyle2LogoPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle2LogoPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2LogoPath", "Chọn logo Style 2")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style2-card-bg" className="text-[11px] text-slate-300">Background Card (Style 2)</Label>
                            {settings.customStyle2CardBgPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle2CardBgPath: ''}))} className="text-[10px] text-emerald-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style2-card-bg" placeholder="Mặc định public/style2/green-bg.jpg" className="text-xs h-8" value={settings.customStyle2CardBgPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle2CardBgPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2CardBgPath", "Chọn Background Card Style 2")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style2-nhay" className="text-[11px] text-slate-300">Icon Nháy (Style 2 - Tùy chọn)</Label>
                            {settings.customStyle2NhayPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle2NhayPath: ''}))} className="text-[10px] text-emerald-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style2-nhay" placeholder="Mặc định: không dùng" className="text-xs h-8" value={settings.customStyle2NhayPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle2NhayPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2NhayPath", "Chọn icon nháy Style 2")}>Chọn</Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3 rounded-xl border border-pink-500/20 bg-pink-500/[0.03] p-2.5">
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="custom-style3-card-bg" className="text-[11px] text-slate-300">Background Card (Style 3 - Hồng)</Label>
                            {settings.customStyle3CardBgPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle3CardBgPath: ''}))} className="text-[10px] text-pink-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="custom-style3-card-bg" placeholder="Mặc định public/style3/bg.png" className="text-xs h-8" value={settings.customStyle3CardBgPath} onChange={(e) => setSettings((c) => ({ ...c, customStyle3CardBgPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle3CardBgPath", "Chọn Background Card Style 3")}>Chọn</Button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Button size="sm" onClick={handleSaveSettings} disabled={savingSettings}>
                      {savingSettings ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />} Lưu
                    </Button>
                    <Button size="sm" variant="outline" onClick={openOutputFolder}><FolderOpen className="size-4" /> Mở</Button>
                  </div>
                </CardContent>
              ) : null}
            </Card>

            {/* Quick feature overview */}
            <Card className="overflow-hidden bg-violet-500/[0.05] border-violet-500/20">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold text-violet-300 flex items-center gap-2">
                  <Sparkles className="size-4" /> Tính năng tự động
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-slate-300 pt-1">
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  <span>Trích xuất caption & hashtag TikTok</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  <span>AI 9Router phân tích sản phẩm giỏ hàng</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  <span>ElevenLabs v3 tags ([excited], [whispers]...)</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  <span>Banner Title 20-30 từ bắt mắt</span>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0 mt-0.5" />
                  <span>Tên file: [Caption] [Hashtags].mp4</span>
                </div>
              </CardContent>
            </Card>
          </aside>

          {/* Main workspace */}
          <section className="space-y-6">
            <Card className="overflow-hidden border-violet-500/40 bg-gradient-to-b from-violet-500/[0.08] to-white/[0.02]">
              <CardHeader className="pb-4">
                <div className="flex flex-col gap-2">
                  <CardTitle className="text-lg font-semibold text-white flex items-center gap-2">
                    <Sparkles className="size-5 text-violet-400" /> Nhập danh sách TikTok & Cấu hình hình ảnh
                  </CardTitle>
                  <CardDescription className="text-slate-300">
                    Dán danh sách các link video TikTok cần xử lý. Hệ thống sẽ tự động thực hiện toàn bộ các bước còn lại.
                  </CardDescription>
                </div>
              </CardHeader>

              <CardContent className="space-y-5">
                {/* TikTok URLs input */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="tiktok-urls" className="text-sm font-medium text-white flex items-center gap-2">
                      Danh sách Link TikTok <span className="text-xs text-violet-400 font-normal">(Mỗi link 1 dòng)</span>
                    </Label>
                    <span className="text-xs text-slate-400">
                      {urlsText.split(/\r?\n/).filter((u) => u.trim()).length} link đã nhập
                    </span>
                  </div>
                  <Textarea
                    id="tiktok-urls"
                    className="min-h-44 font-mono text-sm leading-relaxed border-violet-500/30 bg-black/40 text-slate-100 placeholder:text-slate-500 focus:border-violet-400"
                    value={urlsText}
                    onChange={(e) => setUrlsText(e.target.value)}
                    placeholder={"https://vt.tiktok.com/ZSVFMDUyb/\nhttps://vt.tiktok.com/ZSxxxxxxx/\nhttps://www.tiktok.com/@user/video/1234567890"}
                  />
                </div>

                {/* Geometry and Voice Controls */}
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 p-4 rounded-2xl bg-black/30 border border-white/10">
                  {/* Video Shift Ratio */}
                  <div className="space-y-2">
                    <Label htmlFor="shift-ratio" className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
                      <MoveVertical className="size-3.5 text-cyan-400" /> Tỷ lệ kéo video (Y-offset)
                    </Label>
                    <Input
                      id="shift-ratio"
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      className="bg-black/40 text-sm font-mono"
                      value={videoShiftRatio}
                      onChange={(e) => setVideoShiftRatio(e.target.value)}
                    />
                    <p className="text-[11px] text-slate-400">Mặc định: <strong>0.3333</strong> (1/3 canvas)</p>
                  </div>

                  {/* Video Scale (Zoom) */}
                  <div className="space-y-2">
                    <Label htmlFor="scale-zoom" className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
                      <ZoomIn className="size-3.5 text-emerald-400" /> Giá trị Scale (Zoom video)
                    </Label>
                    <Input
                      id="scale-zoom"
                      type="number"
                      min="0.1"
                      max="3.0"
                      step="0.01"
                      className="bg-black/40 text-sm font-mono"
                      value={videoScale}
                      onChange={(e) => setVideoScale(e.target.value)}
                    />
                    <p className="text-[11px] text-slate-400">Mặc định: <strong>1.08</strong> (Zoom nhẹ 8%)</p>
                  </div>

                  {/* Voice Selector */}
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-slate-200">Giọng đọc (TTS Voice)</Label>
                    <Select value={voiceId} onValueChange={setVoiceId}>
                      <SelectTrigger className="bg-black/40 text-sm">
                        <SelectValue placeholder="Mặc định" />
                      </SelectTrigger>
                      <SelectContent>
                        {voices.map((v) => (
                          <SelectItem key={v.index} value={v.voice_id}>{v.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] text-slate-400">Itera102 / ElevenLabs</p>
                  </div>

                  {/* Layout Style */}
                  <div className="space-y-2">
                    <Label className="text-xs font-medium text-slate-200">Style Template</Label>
                    <Select value={selectedStyle} onValueChange={(v) => setSelectedStyle(v as "style1" | "style2" | "style3")}>
                      <SelectTrigger className="bg-black/40 text-sm">
                        <SelectValue placeholder="Style 1" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="style1">Style 1 (Tone Đỏ)</SelectItem>
                        <SelectItem value="style2">Style 2 (Tone Xanh)</SelectItem>
                        <SelectItem value="style3">Style 3 (Tone Hồng)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] text-slate-400">Khung layout dưới 9:16</p>
                  </div>
                </div>

                <ScriptThemeInput
                  id="ai-video-script-theme"
                  value={scriptTheme}
                  onChange={setScriptTheme}
                  disabled={submitting}
                />

                {/* Tự thêm Showcase + đăng hẹn giờ sau khi gen */}
                <div className="space-y-3">
                  <ShowcaseOptions
                    enabled={autoShowcase}
                    dry={showcaseDry}
                    onEnabledChange={setAutoShowcase}
                    onDryChange={setShowcaseDry}
                    disabled={submitting}
                  />
                  <PostOptions
                    enabled={autoPost}
                    dry={postDry}
                    deleteAfter={postDeleteAfter}
                    onEnabledChange={setAutoPost}
                    onDryChange={setPostDry}
                    onDeleteAfterChange={setPostDeleteAfter}
                    disabled={submitting}
                    refreshKey={job?.status}
                  />
                </div>

                {/* Submit button */}
                <div className="flex items-center justify-between pt-2">
                  <div className="text-xs text-slate-400 flex items-center gap-1.5">
                    <AlertCircle className="size-4 text-amber-400" />
                    <span>Sau khi bấm chạy, bạn có thể theo dõi tiến độ chi tiết từng video ở bảng bên dưới.</span>
                  </div>
                  <Button
                    size="lg"
                    className="bg-violet-600 hover:bg-violet-500 text-white font-medium shadow-[0_0_20px_rgba(139,92,246,0.4)] px-6"
                    onClick={handleSubmit}
                    disabled={submitting}
                  >
                    {submitting ? <LoaderCircle className="size-5 animate-spin mr-2" /> : <Play className="size-5 mr-2" />}
                    Bắt đầu sinh AI Video
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Realtime progress & Results Table */}
            <Card className="overflow-hidden bg-white/[0.045] border-white/10">
              <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between pb-4">
                <div>
                  <CardTitle className="flex items-center gap-2 text-white">
                    <Activity className="size-5 text-emerald-300" /> Tiến độ & Kết quả kết xuất
                  </CardTitle>
                  <CardDescription className="text-slate-300">
                    {jobItems.length > 0 ? `${jobItems.length} video trong hàng đợi xử lý` : "Chưa có tiến trình đang chạy"}
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={openOutputFolder}>
                    <FolderOpen className="size-4 mr-1.5" /> Mở thư mục kết quả
                  </Button>
                </div>
              </CardHeader>

              <CardContent className="space-y-5">
                {/* Overall Progress Bar */}
                <div className="rounded-2xl border border-emerald-400/20 bg-gradient-to-r from-emerald-400/15 to-cyan-400/10 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-medium text-emerald-100">Tiến độ tổng thể</span>
                    <span className="text-xl font-bold text-white">{currentProgress}%</span>
                  </div>
                  <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-teal-300 transition-all duration-500"
                      style={{ width: `${currentProgress}%` }}
                    />
                  </div>
                </div>

                {/* Video list table */}
                <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02]">
                  <div className="max-h-96 overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-white/10 text-left text-xs font-semibold uppercase tracking-wider text-slate-400 bg-white/[0.02]">
                          <th className="px-4 py-3 w-12 text-center">#</th>
                          <th className="px-4 py-3">Thông tin Video / Tên File MP4 Output</th>
                          <th className="px-4 py-3 w-48">Trạng thái</th>
                          <th className="px-4 py-3 w-32 text-right">Hành động</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobItems.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-4 py-8 text-center text-slate-400">
                              Chưa có video nào. Hãy dán link TikTok ở phía trên và bấm <strong>Bắt đầu sinh AI Video</strong>.
                            </td>
                          </tr>
                        ) : (
                          jobItems.map((item) => {
                            const productName = (item.script as Record<string, unknown> | undefined)?.product_name as string || item.product_name_hint || "Đang nhận diện sản phẩm...";
                            const bannerTitle = (item.script as Record<string, unknown> | undefined)?.overlay_banner_title as string;
                            const fileName = item.final_video_path ? item.final_video_path.split(/[\\/]/).pop() : null;

                            return (
                              <tr key={item.index} className="border-b border-white/5 text-white hover:bg-white/[0.02] transition-colors">
                                <td className="px-4 py-3 font-mono text-center text-slate-400 text-xs">{item.index}</td>
                                <td className="px-4 py-3">
                                  <div className="font-semibold text-violet-200 text-sm">
                                    {productName}
                                  </div>
                                  {bannerTitle && (
                                    <p className="text-xs text-amber-200/90 mt-0.5 line-clamp-1">
                                      🎯 {bannerTitle}
                                    </p>
                                  )}
                                  {fileName ? (
                                    <div className="text-xs text-emerald-400 font-mono mt-1 flex items-center gap-1.5 truncate max-w-lg">
                                      <span>🎬 {fileName}</span>
                                    </div>
                                  ) : (
                                    <div className="text-xs text-slate-400 font-mono mt-1 truncate max-w-md">
                                      🔗 {item.url}
                                    </div>
                                  )}
                                </td>
                                <td className="px-4 py-3">
                                  <Badge variant={statusVariant(item.status)} className="text-xs py-1 px-2.5">
                                    {statusLabel(item.status)}
                                  </Badge>
                                  <ShowcaseBadge showcase={item.showcase} />
                                  <PostBadge post={item.post} />
                                  {item.error && (
                                    <p className="mt-1 text-xs text-red-400 line-clamp-2">{item.error}</p>
                                  )}
                                </td>
                                <td className="px-4 py-3 text-right">
                                  {item.final_video_path ? (
                                    <Button
                                      size="sm"
                                      variant="secondary"
                                      className="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 text-xs"
                                      onClick={() => revealPath(item.final_video_path)}
                                    >
                                      <Download className="size-3.5 mr-1.5" /> Mở MP4
                                    </Button>
                                  ) : (
                                    <span className="text-xs text-slate-500">—</span>
                                  )}
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
