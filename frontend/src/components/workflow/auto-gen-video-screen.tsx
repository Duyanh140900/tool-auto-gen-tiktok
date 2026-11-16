"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity, ChevronDown, Download, FolderOpen, Home,
  ListVideo, LoaderCircle, Play, Plus, Save, Sparkles, Trash2,
  Wand2,
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

type AutoGenMode = "review" | "montage";

type ReviewRow = {
  id: number;
  url: string;
  productName: string;
  customScript: string;
  overlayText: string;
  videoShiftRatio: string;
};

const emptyReviewRow = (id: number): ReviewRow => ({
  id,
  url: "",
  productName: "",
  customScript: "",
  overlayText: "",
  videoShiftRatio: "0.3333",
});

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
  if (!status) return "Chưa chạy";
  if (["done", "completed", "success"].includes(status)) return "Hoàn tất";
  if (["failed", "error"].includes(status)) return "Lỗi";
  if (status === "downloading") return "Đang tải";
  if (status === "scripting") return "Phân tích & Script";
  if (status === "tts") return "Lồng tiếng TTS";
  if (status === "planning") return "Lập kế hoạch";
  if (status === "rendering") return "Render";
  if (status === "merging") return "Ghép video 9:16";
  if (["processing", "running"].includes(status)) return "Đang chạy";
  return "Đang chờ";
}

function statusVariant(status?: string | null): "success" | "warning" | "secondary" | "destructive" {
  if (!status) return "secondary";
  if (["done", "completed", "success"].includes(status)) return "success";
  if (["failed", "error"].includes(status)) return "destructive";
  if (["processing", "running", "downloading", "scripting", "tts", "planning", "rendering", "merging"].includes(status)) return "warning";
  return "secondary";
}

const FORM_MEMORY_KEY = "auto-gen-video";

export function AutoGenVideoScreen() {
  const [mode, setMode] = useState<AutoGenMode>("review");

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

  // Review state
  const [reviewRows, setReviewRows] = useState<ReviewRow[]>([emptyReviewRow(1)]);
  const [nextRowId, setNextRowId] = useState(2);
  const [reviewVoiceId, setReviewVoiceId] = useState("google-free");
  const [reviewVideoShiftRatio, setReviewVideoShiftRatio] = useState("0.3333");
  const [autoShowcase, setAutoShowcase] = useState(false);
  const [showcaseDry, setShowcaseDry] = useState(false);
  const [autoPost, setAutoPost] = useState(false);
  const [postDry, setPostDry] = useState(false);
  const [postDeleteAfter, setPostDeleteAfter] = useState(false);
  const [scriptTheme, setScriptTheme] = useState(""); // Chủ đề kịch bản AI, rỗng = AI tự chọn

  // Montage state
  const [montageUrls, setMontageUrls] = useState("");
  const [montageScript, setMontageScript] = useState("");
  const [montageVoiceId, setMontageVoiceId] = useState("google-free");
  const [montageVideoShiftRatio, setMontageVideoShiftRatio] = useState("0.3333");

  // Style selector (shared by review and montage)
  const [selectedStyle, setSelectedStyle] = useState<"style1" | "style2" | "style3">("style1");

  const { snapshot, status: streamStatus, error: streamError } = useJobEvents(true);

  // Cài đặt lần chạy gần nhất (không giữ URL/script vì đổi theo từng lần)
  type FormMemory = {
    mode: AutoGenMode;
    reviewVoiceId: string;
    reviewVideoShiftRatio: string;
    montageVoiceId: string;
    montageVideoShiftRatio: string;
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
    if (m.mode) setMode(m.mode);
    if (m.reviewVideoShiftRatio !== undefined) setReviewVideoShiftRatio(m.reviewVideoShiftRatio);
    if (m.montageVideoShiftRatio !== undefined) setMontageVideoShiftRatio(m.montageVideoShiftRatio);
    if (m.selectedStyle) setSelectedStyle(m.selectedStyle);
    if (m.autoShowcase !== undefined) setAutoShowcase(m.autoShowcase);
    if (m.showcaseDry !== undefined) setShowcaseDry(m.showcaseDry);
    if (m.autoPost !== undefined) setAutoPost(m.autoPost);
    if (m.postDry !== undefined) setPostDry(m.postDry);
    if (m.postDeleteAfter !== undefined) setPostDeleteAfter(m.postDeleteAfter);
    // giọng đọc áp sau khi tải danh sách voice (bootstrap) để không bị ghi đè
  }, []);

  function rememberForm() {
    saveFormMemory<FormMemory>(FORM_MEMORY_KEY, {
      mode,
      reviewVoiceId,
      reviewVideoShiftRatio,
      montageVoiceId,
      montageVideoShiftRatio,
      selectedStyle,
      autoShowcase,
      showcaseDry,
      autoPost,
      postDry,
      postDeleteAfter,
      scriptTheme,
    });
  }

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [settingsData, voicesResponse, jobResponse] = await Promise.all([
          api.getSettings(),
          api.listVoices(),
          api.getJob(),
        ]);
        if (!active) return;
        setSettings(mapSettings(settingsData));
        setVoices(voicesResponse.voices);
        if (voicesResponse.voices && voicesResponse.voices.length > 0) {
          const defaultVoice = voicesResponse.voices.find((v) => v.voice_id === "google-free") || voicesResponse.voices[0];
          setReviewVoiceId(defaultVoice.voice_id);
          setMontageVoiceId(defaultVoice.voice_id);
        }
        if (voicesResponse.voices && voicesResponse.voices.length > 0) {
          const defaultVoice = voicesResponse.voices.find((v) => v.voice_id === "google-free") || voicesResponse.voices[0];
          setReviewVoiceId(defaultVoice.voice_id);
          setMontageVoiceId(defaultVoice.voice_id);
        }
        const saved = loadFormMemory<FormMemory>(FORM_MEMORY_KEY);
        const known = (id?: string) => !!id && (voicesResponse.voices || []).some((v) => v.voice_id === id);
        if (known(saved.reviewVoiceId)) setReviewVoiceId(saved.reviewVoiceId!);
        if (known(saved.montageVoiceId)) setMontageVoiceId(saved.montageVoiceId!);
        if (jobResponse) {
          // job snapshot is available for realtime tracking
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

  useEffect(() => {
    if (streamError) toast({ variant: "warning", title: "Realtime gián đoạn", description: streamError });
  }, [streamError]);

  const job = snapshot ?? null;
  const jobItems = job?.items ?? [];
  const montage = job?.montage ?? null;

  const currentProgress = (() => {
    if (mode === "montage") {
      if (!montage) return 0;
      if (montage.status === "done") return 100;
      if (montage.status === "error") return 100;
      if (montage.status === "rendering") return 85;
      if (montage.status === "planning") return 65;
      if (montage.status === "tts") return 45;
      if (montage.status === "downloading") return 25;
      if (montage.status === "validating") return 10;
      return 0;
    }
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

  // Review row helpers
  function updateReviewRow(id: number, patch: Partial<ReviewRow>) {
    setReviewRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  function addReviewRow() {
    setReviewRows((current) => [...current, emptyReviewRow(nextRowId)]);
    setNextRowId((current) => current + 1);
  }

  function removeReviewRow(id: number) {
    setReviewRows((current) => (current.length > 1 ? current.filter((r) => r.id !== id) : current));
  }

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
      toast({
        variant: "destructive",
        title: "Không chọn được file",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
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

  function parseRatio(raw: string): number {
    const v = parseFloat(raw);
    return isFinite(v) && v >= 0 && v <= 1 ? v : 0.3333;
  }

  async function handleSubmit() {
    setSubmitting(true);
    try {
      if (mode === "review") {
        const items = reviewRows
          .map((row) => ({
            url: row.url.trim(),
            product_name_hint: row.productName.trim() || undefined,
            custom_script: row.customScript.trim() || undefined,
            overlay_text: row.overlayText.trim() || undefined,
            video_shift_ratio: parseRatio(row.videoShiftRatio),
            style: selectedStyle,
          }))
          .filter((r) => r.url.length > 0);

        if (!items.length) {
          toast({ variant: "warning", title: "Thiếu URL", description: "Cần ít nhất một URL TikTok." });
          return;
        }

        await api.autoGen({
          mode: "review",
          items,
          voice_id: reviewVoiceId,
          video_shift_ratio: parseRatio(reviewVideoShiftRatio),
          style: selectedStyle,
          auto_showcase: autoShowcase,
          showcase_dry: showcaseDry,
          auto_post: autoPost,
          post_dry: postDry,
          post_delete_after: postDeleteAfter,
          script_theme: scriptTheme.trim() || undefined,
        });
        rememberForm();
        toast({ variant: "success", title: `Đã tạo job Auto Review (${items.length} video)` });
      } else {
        const urls = montageUrls.split(/\r?\n/).map((u) => u.trim()).filter(Boolean);
        if (urls.length < 2) {
          toast({ variant: "warning", title: "Thiếu URL", description: "Cần ít nhất 2 URL TikTok." });
          return;
        }
        if (!montageScript.trim()) {
          toast({ variant: "warning", title: "Thiếu script", description: "Script TTS là bắt buộc." });
          return;
        }

        await api.autoGen({
          mode: "montage",
          urls,
          script: montageScript.trim(),
          voice_id: montageVoiceId,
          video_shift_ratio: parseRatio(montageVideoShiftRatio),
          style: selectedStyle,
        });
        rememberForm();
        toast({ variant: "success", title: "Đã tạo job Xào video" });
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Tạo job thất bại",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function openOutputFolder() {
    if (!settings.finalOutputDir) {
      toast({ variant: "warning", title: "Chưa có thư mục output" });
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
          <LoaderCircle className="size-4 animate-spin" /> Đang tải...
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen py-6 sm:py-8 lg:py-10">
      <div className="app-shell flex flex-col gap-6 lg:gap-8">
        {/* Header */}
        <header className="glass-panel flex flex-col gap-5 rounded-[2rem] px-5 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="hidden size-12 items-center justify-center rounded-2xl border border-violet-400/30 bg-violet-500/10 text-violet-300 shadow-inner sm:flex">
              <Wand2 className="size-6" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-white">Auto Gen Video</h1>
              <p className="text-sm text-slate-400">
                Tạo video tự động theo lô không cần mở CapCut — hỗ trợ cả Review sản phẩm và Xào video.
              </p>
            </div>
          </div>
          <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-black/15 p-1">
            <Badge variant={streamStatus === "open" ? "success" : streamStatus === "connecting" ? "warning" : "secondary"}>
              WS {streamStatus}
            </Badge>
            <Button asChild variant="ghost"><Link href="/"><Home className="size-4" /> Home</Link></Button>
            <Button asChild variant="ghost"><Link href="/profile-ai-video"><Sparkles className="size-4 text-violet-400" /> Profile AI Video</Link></Button>
            <Button asChild variant="ghost"><Link href="/ai-video"><Sparkles className="size-4" /> AI Video</Link></Button>
            <Button asChild variant="ghost"><Link href="/review"><ListVideo className="size-4" /> Review</Link></Button>
            <Button asChild variant="ghost"><Link href="/montage"><Sparkles className="size-4" /> Xào video</Link></Button>
          </nav>
        </header>

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)]">
          {/* Settings sidebar */}
          <aside className="space-y-5 xl:sticky xl:top-5 xl:self-start">
            <Card className="overflow-hidden bg-white/[0.045]">
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-white">Settings</CardTitle>
                    <CardDescription className="truncate">{settings.finalOutputDir || "Chưa chọn output"}</CardDescription>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setSettingsExpanded((current) => !current)}
                    aria-expanded={settingsExpanded}
                  >
                    <ChevronDown className={`size-4 transition-transform ${settingsExpanded ? "rotate-180" : ""}`} />
                    {settingsExpanded ? "Thu" : "Mở"}
                  </Button>
                </div>
              </CardHeader>
              {settingsExpanded ? (
                <CardContent className="space-y-4 pt-0">
                  <div className="space-y-2">
                    <Label htmlFor="output-dir" className="text-xs font-semibold text-slate-300">Thư mục kết xuất video</Label>
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
                    <Button onClick={handleSaveSettings} disabled={savingSettings}>
                      {savingSettings ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />} Lưu
                    </Button>
                    <Button variant="outline" onClick={openOutputFolder}><FolderOpen className="size-4" /> Mở</Button>
                  </div>
                </CardContent>
              ) : null}
            </Card>
          </aside>

          <section className="space-y-6">
            {/* Mode toggle + form */}
            <Card className="overflow-hidden border-violet-500/30 bg-violet-500/[0.04]">
              <CardHeader>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <CardTitle className="text-white">Cấu hình Auto Gen Video</CardTitle>
                    <CardDescription>
                      {mode === "review"
                        ? "Review video TikTok: Layout 9:16 chuẩn với nửa dưới template và script tiếng Việt."
                        : "Xào nhiều video TikTok thành một video dọc 9:16 với voice-over TTS."}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant={mode === "review" ? "secondary" : "outline"}
                      onClick={() => setMode("review")}
                    >
                      <ListVideo className="size-4" /> Review Video
                    </Button>
                    <Button
                      size="sm"
                      variant={mode === "montage" ? "secondary" : "outline"}
                      onClick={() => setMode("montage")}
                    >
                      <Sparkles className="size-4" /> Montage Clip
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-5">
                {mode === "review" ? (
                  /* ---- Review form ---- */
                  <>
                    <div className="space-y-3">
                      {reviewRows.map((row, index) => (
                        <div
                          key={row.id}
                          className="grid gap-3 rounded-2xl border border-violet-500/20 bg-white/[0.03] p-4 transition hover:border-violet-400/30 lg:grid-cols-[40px_minmax(0,1.3fr)_minmax(0,0.8fr)_44px]"
                        >
                          <div className="flex size-9 items-center justify-center rounded-xl bg-violet-400/20 text-sm font-semibold text-violet-200">
                            {index + 1}
                          </div>
                          <Input
                            value={row.url}
                            onChange={(e) => updateReviewRow(row.id, { url: e.target.value })}
                            placeholder="TikTok URL"
                          />
                          <Input
                            value={row.productName}
                            onChange={(e) => updateReviewRow(row.id, { productName: e.target.value })}
                            placeholder="Tên sản phẩm"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => removeReviewRow(row.id)}
                            disabled={reviewRows.length === 1}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                          <Textarea
                            className="lg:col-start-2 lg:col-end-5"
                            value={row.customScript}
                            onChange={(e) => updateReviewRow(row.id, { customScript: e.target.value })}
                            placeholder="Script tùy chỉnh (bỏ trống = AI tự sinh)"
                          />
                          <div className="lg:col-start-2 lg:col-end-5 flex items-center gap-2">
                            <Label className="whitespace-nowrap text-xs text-white/60">Tỷ lệ kéo video:</Label>
                            <Input
                              type="number"
                              min="0"
                              max="1"
                              step="0.0001"
                              value={row.videoShiftRatio}
                              onChange={(e) => updateReviewRow(row.id, { videoShiftRatio: e.target.value })}
                              className="w-28"
                            />
                          </div>
                          <Textarea
                            className="lg:col-start-2 lg:col-end-5"
                            value={row.overlayText}
                            onChange={(e) => updateReviewRow(row.id, { overlayText: e.target.value })}
                            placeholder="Text hiển thị trên video (bỏ trống = dùng script)"
                          />
                        </div>
                      ))}
                    </div>

                    <div className="flex flex-wrap justify-end gap-2">
                      <Button variant="outline" onClick={addReviewRow}>
                        <Plus className="size-4" /> Thêm dòng
                      </Button>
                    </div>

                    {/* Shared review options */}
                    <div className="grid gap-4 lg:grid-cols-[1fr_200px_200px]">
                      <div className="space-y-2">
                        <Label>Giọng đọc (TTS Voice)</Label>
                        <Select value={reviewVoiceId} onValueChange={setReviewVoiceId}>
                          <SelectTrigger>
                            <SelectValue placeholder="Voice active" />
                          </SelectTrigger>
                          <SelectContent>
                            {voices.map((v) => (
                              <SelectItem key={v.index} value={v.voice_id}>{v.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>Tỷ lệ kéo video chung</Label>
                        <Input
                          type="number"
                          min="0"
                          max="1"
                          step="0.0001"
                          value={reviewVideoShiftRatio}
                          onChange={(e) => setReviewVideoShiftRatio(e.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Style Layout</Label>
                        <Select value={selectedStyle} onValueChange={(v) => setSelectedStyle(v as "style1" | "style2" | "style3")}>
                          <SelectTrigger>
                            <SelectValue placeholder="Style 1" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="style1">Style 1 (Đỏ)</SelectItem>
                            <SelectItem value="style2">Style 2 (Xanh)</SelectItem>
                            <SelectItem value="style3">Style 3 (Hồng)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  </>
                ) : (
                  /* ---- Montage form ---- */
                  <>
                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                      <div className="rounded-2xl border border-violet-500/20 bg-white/[0.04] p-4 shadow-inner shadow-black/10">
                        <Label htmlFor="montage-urls">URL nguồn</Label>
                        <Textarea
                          id="montage-urls"
                          className="mt-3 min-h-52"
                          value={montageUrls}
                          onChange={(e) => setMontageUrls(e.target.value)}
                          placeholder="Mỗi dòng một link TikTok (tối thiểu 2)"
                        />
                      </div>
                      <div className="rounded-2xl border border-violet-500/20 bg-white/[0.04] p-4 shadow-inner shadow-black/10 space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="montage-voice">Voice</Label>
                          <Select value={montageVoiceId} onValueChange={setMontageVoiceId}>
                            <SelectTrigger id="montage-voice">
                              <SelectValue placeholder="Voice active" />
                            </SelectTrigger>
                            <SelectContent>
                              {voices.map((v) => (
                                <SelectItem key={v.index} value={v.voice_id}>{v.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label>Tỷ lệ kéo video</Label>
                          <Input
                            type="number"
                            min="0"
                            max="1"
                            step="0.0001"
                            value={montageVideoShiftRatio}
                            onChange={(e) => setMontageVideoShiftRatio(e.target.value)}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label>Style</Label>
                          <Select value={selectedStyle} onValueChange={(v) => setSelectedStyle(v as "style1" | "style2" | "style3")}>
                            <SelectTrigger>
                              <SelectValue placeholder="Style 1" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="style1">Style 1 (Đỏ)</SelectItem>
                              <SelectItem value="style2">Style 2 (Xanh)</SelectItem>
                              <SelectItem value="style3">Style 3 (Hồng)</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-2xl border border-violet-500/20 bg-white/[0.04] p-4 shadow-inner shadow-black/10">
                      <Label htmlFor="montage-script">Script TTS</Label>
                      <Textarea
                        id="montage-script"
                        className="mt-3 min-h-40"
                        value={montageScript}
                        onChange={(e) => setMontageScript(e.target.value)}
                        placeholder="Nội dung voice-over cho toàn bộ video (bắt buộc)"
                      />
                    </div>
                  </>
                )}

                {mode === "review" ? (
                  <>
                    <ScriptThemeInput
                      id="auto-gen-script-theme"
                      value={scriptTheme}
                      onChange={setScriptTheme}
                      disabled={submitting}
                    />
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
                      onDeleteAfterChange={setPostDeleteAfter}
                      onEnabledChange={setAutoPost}
                      onDryChange={setPostDry}
                      disabled={submitting}
                      refreshKey={snapshot?.status}
                    />
                  </>
                ) : null}

                <div className="flex justify-end">
                  <Button
                    className="bg-violet-500 text-white hover:bg-violet-400"
                    onClick={handleSubmit}
                    disabled={submitting}
                  >
                    {submitting ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}
                    {mode === "review" ? "Bắt đầu Auto Gen Video" : "Chạy Xào video"}
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Status card */}
            <Card className="overflow-hidden bg-white/[0.045]">
              <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-white">
                    <Activity className="size-5 text-emerald-300" /> Trạng thái & Kết quả
                  </CardTitle>
                  <CardDescription>
                    {mode === "review"
                      ? `${jobItems.length} video trong hàng đợi`
                      : `${montage?.urls?.length ?? 0} nguồn`}
                  </CardDescription>
                </div>
                <Button variant="outline" onClick={openOutputFolder}><FolderOpen className="size-4" /> Mở thư mục kết quả</Button>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Progress bar */}
                <div className="rounded-2xl border border-emerald-400/20 bg-gradient-to-r from-emerald-400/15 to-cyan-400/10 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm text-emerald-100">Tiến độ</span>
                    <span className="text-xl font-semibold text-white">{currentProgress}%</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-emerald-400" style={{ width: `${currentProgress}%` }} />
                  </div>
                </div>

                {mode === "review" ? (
                  <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03]">
                    <div className="max-h-80 overflow-y-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-white/10 text-left text-slate-400">
                            <th className="px-4 py-2">#</th>
                            <th className="px-4 py-2">Sản phẩm / URL</th>
                            <th className="px-4 py-2">Trạng thái</th>
                            <th className="px-4 py-2 text-right">Output</th>
                          </tr>
                        </thead>
                        <tbody>
                          {jobItems.length === 0 ? (
                            <tr>
                              <td colSpan={4} className="px-4 py-6 text-center text-slate-400">Chưa có video nào trong danh sách.</td>
                            </tr>
                          ) : jobItems.map((item) => (
                            <tr key={item.index} className="border-b border-white/5 text-white">
                              <td className="px-4 py-2.5 font-medium text-slate-400">{item.index}</td>
                              <td className="px-4 py-2.5">
                                <div className="font-medium text-violet-200">
                                  {item.product_name_hint || (item.script as Record<string, unknown> | undefined)?.product_name as string || "Video review"}
                                </div>
                                {item.final_video_path && (
                                  <div className="text-xs text-slate-400 font-mono mt-0.5 truncate max-w-md">
                                    📁 {item.final_video_path.split(/[\\/]/).pop()}
                                  </div>
                                )}
                              </td>
                              <td className="px-4 py-2.5">
                                <Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge>
                                <ShowcaseBadge showcase={item.showcase} />
                                <PostBadge post={item.post} />
                                {item.error && <p className="mt-1 text-xs text-red-400">{item.error}</p>}
                              </td>
                              <td className="px-4 py-2.5 text-right">
                                {item.final_video_path ? (
                                  <Button size="sm" variant="secondary" onClick={() => revealPath(item.final_video_path)}>
                                    <Download className="size-4 mr-1.5" /> Mở MP4
                                  </Button>
                                ) : (
                                  <span className="text-xs text-slate-500">—</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                      <div className="text-sm text-slate-400">Trạng thái</div>
                      <div className="mt-2 text-xl font-semibold text-white">{statusLabel(montage?.status)}</div>
                      <p className="mt-2 text-sm text-slate-300">{montage?.message ?? "Chưa có job."}</p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                      <div className="text-sm text-slate-400">Output MP4</div>
                      <p className="mt-2 truncate text-sm text-white">{montage?.final_video_path ?? "—"}</p>
                      <Button
                        className="mt-3"
                        size="sm"
                        variant="secondary"
                        disabled={!montage?.final_video_path}
                        onClick={() => revealPath(montage?.final_video_path)}
                      >
                        <Download className="size-4" /> Mở file
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </section>
        </div>
      </div>
    </main>
  );
}
