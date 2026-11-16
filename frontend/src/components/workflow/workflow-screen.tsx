"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import {
  Activity,
  ChevronDown,
  Download,
  FolderOpen,
  Home,
  ListVideo,
  LoaderCircle,
  Play,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useJobEvents } from "@/hooks/use-job-events";
import { toast } from "@/hooks/use-toast";
import {
  api,
  ApiError,
  type BatchResultItem,
  type JobSnapshot,
  type SettingsResponse,
  type VoiceItem,
} from "@/lib/api";

type Workflow = "review" | "montage";

type BatchRow = {
  id: number;
  url: string;
  productName: string;
  customScript: string;
  videoShiftRatio: string;
  videoScale: string;
};

type SettingsForm = {
  finalOutputDir: string;
  itera102VoiceId: string;
  itera102Speed: number;
  itera102Stability: number;
  itera102SimilarityBoost: number;
  itera102Style: number;
  itera102UseSpeakerBoost: boolean;
  customStyle1LogoPath?: string;
  customStyle1CardBgPath?: string;
  customStyle1NhayPath?: string;
  customStyle2LogoPath?: string;
  customStyle2CardBgPath?: string;
  customStyle2NhayPath?: string;
  customStyle3LogoPath?: string;
  customStyle3CardBgPath?: string;
  customStyle3NhayPath?: string;
};

const emptyRow = (id: number): BatchRow => ({
  id,
  url: "",
  productName: "",
  customScript: "",
  videoShiftRatio: "0.3333",
  videoScale: "1.08",
});

function mapSettings(data: SettingsResponse): SettingsForm {
  return {
    finalOutputDir: data.final_output_dir || "",
    itera102VoiceId: data.itera102_voice_id || "",
    itera102Speed: data.itera102_speed,
    itera102Stability: data.itera102_stability,
    itera102SimilarityBoost: data.itera102_similarity_boost,
    itera102Style: data.itera102_style,
    itera102UseSpeakerBoost: data.itera102_use_speaker_boost,
    customStyle1LogoPath: data.custom_style1_logo_path || data.custom_logo_path || "",
    customStyle1CardBgPath: data.custom_style1_card_bg_path || data.custom_card_bg_path || "",
    customStyle1NhayPath: data.custom_style1_nhay_path || data.custom_nhay_path || "",
    customStyle2LogoPath: data.custom_style2_logo_path || "",
    customStyle2CardBgPath: data.custom_style2_card_bg_path || "",
    customStyle2NhayPath: data.custom_style2_nhay_path || "",
    customStyle3LogoPath: data.custom_style3_logo_path || "",
    customStyle3CardBgPath: data.custom_style3_card_bg_path || "",
    customStyle3NhayPath: data.custom_style3_nhay_path || "",
  };
}

function extractJob(snapshot: JobSnapshot | { job: JobSnapshot | null } | null): JobSnapshot | null {
  if (!snapshot) return null;
  return "job" in snapshot ? snapshot.job : snapshot;
}

function statusLabel(status?: string | null) {
  if (!status) return "Chưa chạy";
  if (["done", "completed", "success"].includes(status)) return "Hoàn tất";
  if (["failed", "error"].includes(status)) return "Lỗi";
  if (status === "downloading") return "Đang tải";
  if (status === "scripting") return "Script";
  if (status === "tts") return "TTS";
  if (status === "planning") return "Kế hoạch";
  if (status === "rendering") return "Render";
  if (status === "merging") return "Ghép";
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

function deriveItemProgress(item: BatchResultItem) {
  if (["done", "completed", "success"].includes(item.status)) return 100;
  if (["failed", "error"].includes(item.status)) return 100;
  if (item.status === "merging") return 85;
  if (item.status === "tts") return 65;
  if (item.status === "scripting") return 40;
  if (item.status === "downloading") return 20;
  return 0;
}

function deriveItemMessage(item: BatchResultItem) {
  if (item.error) return item.error;
  if (item.final_video_path) return item.final_video_path;
  if (item.status === "merging") return "Đang ghép video";
  if (item.status === "tts") return "Đang tạo giọng đọc";
  if (item.status === "scripting") return "Đang viết script";
  if (item.status === "downloading") return "Đang tải video gốc";
  return "Đang chờ xử lý";
}

function montageProgress(status?: string | null) {
  if (!status) return 0;
  if (["done", "completed", "success"].includes(status)) return 100;
  if (["failed", "error"].includes(status)) return 100;
  if (status === "rendering") return 85;
  if (status === "planning") return 65;
  if (status === "tts") return 45;
  if (status === "downloading") return 25;
  if (status === "validating") return 10;
  return 0;
}

export function WorkflowScreen({ workflow }: { workflow: Workflow }) {
  const [loading, setLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submittingMontage, setSubmittingMontage] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [settings, setSettings] = useState<SettingsForm>({
    finalOutputDir: "",
    itera102VoiceId: "",
    itera102Speed: 1,
    itera102Stability: 0.75,
    itera102SimilarityBoost: 0.75,
    itera102Style: 0,
    itera102UseSpeakerBoost: true,
  });
  const [voices, setVoices] = useState<VoiceItem[]>([]);
  const [rows, setRows] = useState<BatchRow[]>([emptyRow(1)]);
  const [nextId, setNextId] = useState(2);
  const [maxConcurrent, setMaxConcurrent] = useState("1");
  const [montageUrls, setMontageUrls] = useState("");
  const [montageScript, setMontageScript] = useState("");
  const [montageVoiceId, setMontageVoiceId] = useState("default");
  const [montageVideoShiftRatio, setMontageVideoShiftRatio] = useState("0.3333");
  const [initialJob, setInitialJob] = useState<JobSnapshot | null>(null);

  const { snapshot, status: streamStatus, error: streamError } = useJobEvents(true);

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
        setInitialJob(extractJob(jobResponse));
      } catch (error) {
        toast({ variant: "destructive", title: "Không tải được dữ liệu", description: error instanceof ApiError ? error.message : "Lỗi khởi tạo" });
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

  const job = snapshot ?? initialJob;
  const jobItems = job?.items ?? [];
  const montage = job?.montage ?? null;

  const currentProgress = (() => {
    if (workflow === "montage") return montageProgress(montage?.status);
    if (!jobItems.length) return 0;
    const total = jobItems.reduce((sum, item) => sum + deriveItemProgress(item), 0);
    return Math.round(total / jobItems.length);
  })();

  function addRow() {
    setRows((current) => [...current, emptyRow(nextId)]);
    setNextId((current) => current + 1);
  }

  function removeRow(id: number) {
    setRows((current) => (current.length > 1 ? current.filter((item) => item.id !== id) : current));
  }

  function updateRow(id: number, patch: Partial<BatchRow>) {
    setRows((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  async function handlePickFolder() {
    try {
      const response = await api.pickFolder();
      if (response.path) setSettings((current) => ({ ...current, finalOutputDir: response.path ?? current.finalOutputDir }));
    } catch (error) {
      toast({ variant: "destructive", title: "Không chọn được thư mục", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    }
  }

  const [settingsStyleTab, setSettingsStyleTab] = useState<"style1" | "style2">("style1");

  async function handlePickFile(field: keyof SettingsForm, title: string) {
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
        itera102_speed: Number(settings.itera102Speed),
        itera102_stability: Number(settings.itera102Stability),
        itera102_similarity_boost: Number(settings.itera102SimilarityBoost),
        itera102_style: Number(settings.itera102Style),
        itera102_use_speaker_boost: settings.itera102UseSpeakerBoost,
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

  async function handleSubmitBatch() {
    function parseRatio(raw: string): number {
      const v = parseFloat(raw);
      return isFinite(v) && v >= 0 && v <= 1 ? v : 0.3333;
    }
    const items = rows
      .map((row) => ({
        url: row.url.trim(),
        product_name_hint: row.productName.trim() || undefined,
        custom_script: row.customScript.trim() || undefined,
        video_shift_ratio: parseRatio(row.videoShiftRatio),
        video_scale: parseFloat(row.videoScale) || 1.08,
        style: "style1",
      }))
      .filter((item) => item.url.length > 0);

    if (!items.length) {
      toast({ variant: "warning", title: "Thiếu dữ liệu", description: "Cần ít nhất một URL TikTok." });
      return;
    }

    setSubmitting(true);
    try {
      await api.createBatch({ items, max_concurrent: Number(maxConcurrent) });
      toast({ variant: "success", title: "Đã tạo batch review" });
    } catch (error) {
      toast({ variant: "destructive", title: "Tạo batch thất bại", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmitMontage() {
    const urls = montageUrls.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    if (urls.length < 2) {
      toast({ variant: "warning", title: "Thiếu URL", description: "Cần tối thiểu 2 URL TikTok để xào video." });
      return;
    }
    if (!montageScript.trim()) {
      toast({ variant: "warning", title: "Thiếu script", description: "Script TTS là bắt buộc cho workflow xào video." });
      return;
    }

    const voiceId = montageVoiceId === "default" ? undefined : montageVoiceId;
    const shiftRatio = (() => {
      const v = parseFloat(montageVideoShiftRatio);
      return isFinite(v) && v >= 0 && v <= 1 ? v : 0.3333;
    })();

    setSubmittingMontage(true);
    try {
      await api.createMontage({ urls, script: montageScript.trim(), voice_id: voiceId, video_shift_ratio: shiftRatio, mode: "live" });
      toast({ variant: "success", title: "Đã tạo job xào video" });
    } catch (error) {
      toast({ variant: "destructive", title: "Tạo job xào thất bại", description: error instanceof Error ? error.message : "Lỗi không xác định" });
    } finally {
      setSubmittingMontage(false);
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
        <div className="glass-panel flex items-center gap-3 rounded-2xl px-5 py-4 text-sm text-slate-200"><LoaderCircle className="size-4 animate-spin" /> Đang tải...</div>
      </main>
    );
  }

  return (
    <main className="min-h-screen py-6 sm:py-8 lg:py-10">
      <div className="app-shell flex flex-col gap-6 lg:gap-8">
        <header className="glass-panel flex flex-col gap-5 rounded-[2rem] px-5 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="hidden size-12 items-center justify-center rounded-2xl border border-white/10 bg-white/10 text-primary shadow-inner sm:flex">
              {workflow === "review" ? <ListVideo className="size-6" /> : <Sparkles className="size-6" />}
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-white">{workflow === "review" ? "Review hiện tại" : "Xào video"}</h1>
              <p className="text-sm text-slate-400">{workflow === "review" ? "Tạo video review từ TikTok và TTS." : "Ghép nhiều nguồn TikTok thành video dọc có TTS."}</p>
            </div>
          </div>
          <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-black/15 p-1">
            <Badge variant={streamStatus === "open" ? "success" : streamStatus === "connecting" ? "warning" : "secondary"}>WS {streamStatus}</Badge>
            <Button asChild variant="ghost"><Link href="/"><Home className="size-4" /> Home</Link></Button>
            <Button asChild variant="ghost"><Link href="/ai-video"><Sparkles className="size-4 text-violet-400" /> AI Video</Link></Button>
            <Button asChild variant="ghost"><Link href="/profile-ai-video"><Sparkles className="size-4 text-violet-400" /> Profile AI Video</Link></Button>
            <Button asChild variant={workflow === "review" ? "secondary" : "ghost"}><Link href="/review"><ListVideo className="size-4" /> Review</Link></Button>
            <Button asChild variant={workflow === "montage" ? "secondary" : "ghost"}><Link href="/montage"><Sparkles className="size-4" /> Xào video</Link></Button>
            <Button asChild variant="ghost"><Link href="/auto-gen-video"><Wand2 className="size-4" /> Auto gen</Link></Button>
          </nav>
        </header>

        <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)]">
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
                    aria-controls="settings-panel"
                  >
                    <ChevronDown className={`size-4 transition-transform ${settingsExpanded ? "rotate-180" : ""}`} />
                    {settingsExpanded ? "Thu" : "Mở"}
                  </Button>
                </div>
              </CardHeader>
              {settingsExpanded ? <CardContent id="settings-panel" className="space-y-4 pt-0">
                <div className="space-y-2">
                  <Label htmlFor="output-dir">Output</Label>
                  <div className="flex gap-2">
                    <Input id="output-dir" value={settings.finalOutputDir} onChange={(event) => setSettings((current) => ({ ...current, finalOutputDir: event.target.value }))} />
                    <Button size="icon" variant="outline" onClick={handlePickFolder} aria-label="Chọn thư mục"><FolderOpen className="size-4" /></Button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="voice-id">Itera102 voice ID</Label>
                  <Input id="voice-id" value={settings.itera102VoiceId} onChange={(event) => setSettings((current) => ({ ...current, itera102VoiceId: event.target.value }))} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                  <div className="space-y-2">
                    <Label htmlFor="speed">Speed</Label>
                    <Input id="speed" type="number" min="0.7" max="1.2" step="0.05" value={settings.itera102Speed} onChange={(event) => setSettings((current) => ({ ...current, itera102Speed: parseFloat(event.target.value) || 1 }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="stability">Stability</Label>
                    <Input id="stability" type="number" min="0" max="1" step="0.05" value={settings.itera102Stability} onChange={(event) => setSettings((current) => ({ ...current, itera102Stability: parseFloat(event.target.value) || 0.75 }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="similarity">Similarity</Label>
                    <Input id="similarity" type="number" min="0" max="1" step="0.05" value={settings.itera102SimilarityBoost} onChange={(event) => setSettings((current) => ({ ...current, itera102SimilarityBoost: parseFloat(event.target.value) || 0.75 }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="style">Style</Label>
                    <Input id="style" type="number" min="0" max="1" step="0.05" value={settings.itera102Style} onChange={(event) => setSettings((current) => ({ ...current, itera102Style: parseFloat(event.target.value) || 0 }))} />
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-black/15 p-3">
                  <Checkbox id="speaker-boost" checked={settings.itera102UseSpeakerBoost} onCheckedChange={(checked) => setSettings((current) => ({ ...current, itera102UseSpeakerBoost: Boolean(checked) }))} />
                  <Label htmlFor="speaker-boost">Speaker boost</Label>
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
                          <Input id="custom-style1-logo" placeholder="Mặc định public/logo_tiembachhoa.png" className="text-xs h-8" value={settings.customStyle1LogoPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1LogoPath: e.target.value }))} />
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
                          <Input id="custom-style1-card-bg" placeholder="Mặc định public/red-bg.png" className="text-xs h-8" value={settings.customStyle1CardBgPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1CardBgPath: e.target.value }))} />
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
                          <Input id="custom-style1-nhay" placeholder="Mặc định public/nhay.png" className="text-xs h-8" value={settings.customStyle1NhayPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1NhayPath: e.target.value }))} />
                          <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1NhayPath", "Chọn icon nháy Style 1")}>Chọn</Button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] p-2.5">
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <Label htmlFor="custom-style2-logo" className="text-[11px] text-slate-300">Logo (Style 2)</Label>
                          {settings.customStyle2LogoPath ? (
                            <button type="button" onClick={() => setSettings(c => ({...c, customStyle2LogoPath: ''}))} className="text-[10px] text-emerald-400 hover:underline">Mặc định</button>
                          ) : null}
                        </div>
                        <div className="flex gap-1.5">
                          <Input id="custom-style2-logo" placeholder="Mặc định public/style2/logo.png" className="text-xs h-8" value={settings.customStyle2LogoPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle2LogoPath: e.target.value }))} />
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
                          <Input id="custom-style2-card-bg" placeholder="Mặc định public/style2/green-bg.jpg" className="text-xs h-8" value={settings.customStyle2CardBgPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle2CardBgPath: e.target.value }))} />
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
                          <Input id="custom-style2-nhay" placeholder="Mặc định: không dùng" className="text-xs h-8" value={settings.customStyle2NhayPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle2NhayPath: e.target.value }))} />
                          <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2NhayPath", "Chọn icon nháy Style 2")}>Chọn</Button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button onClick={handleSaveSettings} disabled={savingSettings}>{savingSettings ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />} Lưu</Button>
                  <Button variant="outline" onClick={openOutputFolder}><FolderOpen className="size-4" /> Mở</Button>
                </div>
              </CardContent> : null}
            </Card>
          </aside>

          <section className="space-y-6">
            {workflow === "review" ? (
              <Card className="overflow-hidden bg-white/[0.045]">
                <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <CardTitle className="text-white">Batch input</CardTitle>
                    <CardDescription>Mỗi dòng một video review.</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Label htmlFor="max-concurrent" className="text-sm">Luồng</Label>
                    <Select value={maxConcurrent} onValueChange={setMaxConcurrent}>
                      <SelectTrigger id="max-concurrent" className="w-28"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="1">1</SelectItem><SelectItem value="2">2</SelectItem><SelectItem value="3">3</SelectItem></SelectContent>
                    </Select>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="space-y-3">
                    {rows.map((row, index) => (
                        <div key={row.id} className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.035] p-4 transition hover:border-white/20 hover:bg-white/[0.055] lg:grid-cols-[40px_minmax(0,1.3fr)_minmax(0,0.8fr)_44px]">
                        <div className="flex size-9 items-center justify-center rounded-xl bg-white/10 text-sm font-semibold text-white">{index + 1}</div>
                        <Input value={row.url} onChange={(event) => updateRow(row.id, { url: event.target.value })} placeholder="TikTok URL" />
                        <Input value={row.productName} onChange={(event) => updateRow(row.id, { productName: event.target.value })} placeholder="Tên sản phẩm" />
                        <Button variant="ghost" size="icon" onClick={() => removeRow(row.id)} disabled={rows.length === 1}><Trash2 className="size-4" /></Button>
                        <Textarea className="lg:col-start-2 lg:col-end-5" value={row.customScript} onChange={(event) => updateRow(row.id, { customScript: event.target.value })} placeholder="Script tùy chọn" />
                        <div className="lg:col-start-2 lg:col-end-5 flex items-center gap-2">
                          <Label className="whitespace-nowrap text-xs text-white/60">Tỷ lệ kéo video:</Label>
                          <Input
                            type="number"
                            min="0"
                            max="1"
                            step="0.0001"
                            value={row.videoShiftRatio}
                            onChange={(event) => updateRow(row.id, { videoShiftRatio: event.target.value })}
                            className="w-28"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap justify-end gap-3">
                    <Button variant="outline" onClick={addRow}><Plus className="size-4" /> Thêm dòng</Button>
                    <Button onClick={handleSubmitBatch} disabled={submitting}>{submitting ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />} Chạy review</Button>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Card className="overflow-hidden bg-white/[0.045]">
                <CardHeader>
                  <CardTitle className="text-white">Xào video TikTok</CardTitle>
                  <CardDescription>Tối thiểu 2 URL và script bắt buộc.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 shadow-inner shadow-black/10">
                      <Label htmlFor="montage-urls">URL nguồn</Label>
                      <Textarea id="montage-urls" className="mt-3 min-h-52" value={montageUrls} onChange={(event) => setMontageUrls(event.target.value)} placeholder="Mỗi dòng một link TikTok" />
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 shadow-inner shadow-black/10">
                      <Label htmlFor="montage-voice">Voice</Label>
                      <Select value={montageVoiceId} onValueChange={setMontageVoiceId}>
                        <SelectTrigger id="montage-voice" className="mt-3"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="default">Voice active</SelectItem>
                          {voices.map((voice) => <SelectItem key={voice.index} value={voice.voice_id}>{voice.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <div className="mt-3 flex items-center gap-2">
                        <Label className="whitespace-nowrap text-xs text-white/60">Tỷ lệ kéo video:</Label>
                        <Input
                          type="number"
                          min="0"
                          max="1"
                          step="0.0001"
                          value={montageVideoShiftRatio}
                          onChange={(event) => setMontageVideoShiftRatio(event.target.value)}
                          className="w-28"
                        />
                      </div>
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 shadow-inner shadow-black/10">
                    <Label htmlFor="montage-script">Script TTS</Label>
                    <Textarea id="montage-script" className="mt-3 min-h-60" value={montageScript} onChange={(event) => setMontageScript(event.target.value)} placeholder="Nội dung voice-over" />
                  </div>
                  <div className="flex justify-end">
                    <Button onClick={handleSubmitMontage} disabled={submittingMontage}>{submittingMontage ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />} Chạy xào video</Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <Card className="overflow-hidden bg-white/[0.045]">
              <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-white"><Activity className="size-5 text-emerald-300" /> Trạng thái</CardTitle>
                  <CardDescription>{workflow === "review" ? `${jobItems.length} item` : `${montage?.urls.length ?? 0} nguồn`}</CardDescription>
                </div>
                <Button variant="outline" onClick={openOutputFolder}><FolderOpen className="size-4" /> Mở output</Button>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="rounded-2xl border border-emerald-400/20 bg-gradient-to-r from-emerald-400/15 to-cyan-400/10 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm text-emerald-100">Tiến độ</span>
                    <span className="text-xl font-semibold text-white">{currentProgress}%</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-emerald-400" style={{ width: `${currentProgress}%` }} /></div>
                </div>

                {workflow === "review" ? (
                  <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03]">
                    <ScrollArea className="w-full">
                      <div className="min-w-[820px]">
                        <Table>
                          <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Sản phẩm</TableHead><TableHead>Trạng thái</TableHead><TableHead>Thông báo</TableHead><TableHead>Output</TableHead></TableRow></TableHeader>
                          <TableBody>
                            {jobItems.length === 0 ? <TableRow><TableCell colSpan={5} className="text-center text-slate-400">Chưa có job.</TableCell></TableRow> : null}
                            {jobItems.map((item) => (
                              <TableRow key={item.index}>
                                <TableCell className="font-medium text-white">{item.index}</TableCell>
                                <TableCell>{item.product_name_hint || "—"}</TableCell>
                                <TableCell><Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge></TableCell>
                                <TableCell><span className="block max-w-[240px] truncate">{deriveItemMessage(item)}</span></TableCell>
                                <TableCell>
                                  {item.final_video_path ? <Button size="sm" variant="ghost" onClick={() => revealPath(item.final_video_path)}><Download className="size-4" /> MP4</Button> : "—"}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </ScrollArea>
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
                      <Button className="mt-3" size="sm" variant="secondary" disabled={!montage?.final_video_path} onClick={() => revealPath(montage?.final_video_path)}><Download className="size-4" /> Mở file</Button>
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
