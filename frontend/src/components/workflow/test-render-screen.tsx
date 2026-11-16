"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronDown, FlaskConical, FolderOpen, Home, ListVideo, LoaderCircle, Plus, Save, Sparkles, Trash2, Wand2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/hooks/use-toast";
import { api, type SettingsResponse } from "@/lib/api";

type TestRow = {
  id: number;
  url: string;
  customScript: string;
};

const emptyRow = (id: number): TestRow => ({
  id,
  url: "",
  customScript: "",
});

export function TestRenderScreen() {
  const [rows, setRows] = useState<TestRow[]>([emptyRow(1)]);
  const [nextRowId, setNextRowId] = useState(2);
  const [mode, setMode] = useState<"review" | "montage">("review");
  const [settings, setSettings] = useState<{
    finalOutputDir: string;
    customStyle1LogoPath?: string;
    customStyle1CardBgPath?: string;
    customStyle1NhayPath?: string;
    customStyle2LogoPath?: string;
    customStyle2CardBgPath?: string;
    customStyle2NhayPath?: string;
    customStyle3LogoPath?: string;
    customStyle3CardBgPath?: string;
    customStyle3NhayPath?: string;
  }>({
    finalOutputDir: "",
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
  const [loading, setLoading] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [settingsStyleTab, setSettingsStyleTab] = useState<"style1" | "style2" | "style3">("style1");
  const [videoShiftRatio, setVideoShiftRatio] = useState("0.3333");
  const [selectedStyle, setSelectedStyle] = useState<"style1" | "style2" | "style3">("style1");

  useEffect(() => {
    async function bootstrap() {
      try {
        const settingsData = await api.getSettings();
        setSettings({
          finalOutputDir: settingsData.final_output_dir || "",
          customStyle1LogoPath: settingsData.custom_style1_logo_path || settingsData.custom_logo_path || "",
          customStyle1CardBgPath: settingsData.custom_style1_card_bg_path || settingsData.custom_card_bg_path || "",
          customStyle1NhayPath: settingsData.custom_style1_nhay_path || settingsData.custom_nhay_path || "",
          customStyle2LogoPath: settingsData.custom_style2_logo_path || "",
          customStyle2CardBgPath: settingsData.custom_style2_card_bg_path || "",
          customStyle2NhayPath: settingsData.custom_style2_nhay_path || "",
          customStyle3LogoPath: settingsData.custom_style3_logo_path || "",
          customStyle3CardBgPath: settingsData.custom_style3_card_bg_path || "",
          customStyle3NhayPath: settingsData.custom_style3_nhay_path || "",
        });
      } catch (error) {
        toast({
          variant: "destructive",
          title: "Không lấy được cấu hình",
          description: error instanceof Error ? error.message : "Lỗi không xác định",
        });
      } finally {
        setLoading(false);
      }
    }
    bootstrap();
  }, []);

  function addRow() {
    setRows((current) => [...current, emptyRow(nextRowId)]);
    setNextRowId((current) => current + 1);
  }

  function removeRow(id: number) {
    setRows((current) => (current.length > 1 ? current.filter((r) => r.id !== id) : current));
  }

  function updateRow(id: number, patch: Partial<TestRow>) {
    setRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }

  async function handlePickFolder() {
    try {
      const response = await api.pickFolder();
      if (response.path) {
        setSettings((current) => ({ ...current, finalOutputDir: response.path ?? current.finalOutputDir }));
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Không chọn được thư mục",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
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
      toast({ variant: "success", title: "Đã lưu cài đặt" });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Không lưu được cài đặt",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
    } finally {
      setSavingSettings(false);
    }
  }

  async function handleTestRender() {
    setSubmitting(true);
    try {
      const urls = rows.map((r) => r.url.trim()).filter(Boolean);
      const script = rows[0]?.customScript?.trim() || "NỘI DUNG TEST BỐ CỤC 9:16 VÀ 4 ẢNH OVERLAY (KHÔNG TỐN CREDIT TTS)";

      if (!urls.length) {
        toast({
          variant: "warning",
          title: "Thiếu URL TikTok",
          description: "Vui lòng nhập ít nhất 1 đường dẫn TikTok để chạy test render.",
        });
        return;
      }

      const ratioV = parseFloat(videoShiftRatio);
      const ratio = isFinite(ratioV) && ratioV >= 0 && ratioV <= 1 ? ratioV : 0.3333;
      const res = await api.testRender({
        mode,
        urls,
        script,
        duration_sec: 10,
        video_shift_ratio: ratio,
        style: selectedStyle,
      });

      toast({
        variant: "success",
        title: "Render thử nghiệm thành công",
        description: res.message,
      });

      if (res.final_video_path) {
        await api.revealFile(res.final_video_path);
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Lỗi test render",
        description: error instanceof Error ? error.message : "Vui lòng thử lại sau",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function openOutputFolder() {
    if (!settings.finalOutputDir) {
      toast({ variant: "warning", title: "Chưa chọn thư mục output" });
      return;
    }
    try {
      await api.openFolder(settings.finalOutputDir);
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Không mở được thư mục",
        description: error instanceof Error ? error.message : "Lỗi không xác định",
      });
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-6 py-10">
        <div className="glass-panel flex items-center gap-3 rounded-2xl px-5 py-4 text-sm text-slate-200">
          <LoaderCircle className="size-4 animate-spin" /> Đang tải màn test...
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen py-6 sm:py-8 lg:py-10">
      <div className="app-shell flex flex-col gap-6 lg:gap-8">
        <header className="glass-panel flex flex-col gap-5 rounded-[2rem] px-5 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="hidden size-12 items-center justify-center rounded-2xl border border-amber-400/30 bg-amber-500/10 text-amber-300 shadow-inner sm:flex">
              <FlaskConical className="size-6" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-white">Màn Test Render Layout (Miễn phí credit)</h1>
              <p className="text-sm text-slate-400">
                Thử nghiệm dựng video 9:16 + 4 ảnh overlay + căn dòng script tiếng Việt mà KHÔNG dùng API voice.
              </p>
            </div>
          </div>
          <nav className="flex flex-wrap items-center gap-2 rounded-2xl border border-white/10 bg-black/15 p-1">
            <Badge variant="outline" className="border-amber-400/40 text-amber-300">
              Silent Audio Mode
            </Badge>
            <Button asChild variant="ghost">
              <Link href="/">
                <Home className="size-4" /> Home
              </Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/review">
                <ListVideo className="size-4" /> Review
              </Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/montage">
                <Sparkles className="size-4" /> Xào video
              </Link>
            </Button>
            <Button asChild variant="secondary" className="bg-amber-500/20 text-amber-200">
              <Link href="/test-render">
                <FlaskConical className="size-4" /> Test Render
              </Link>
            </Button>
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
                  >
                    <ChevronDown className={`size-4 transition-transform ${settingsExpanded ? "rotate-180" : ""}`} />
                    {settingsExpanded ? "Thu" : "Mở"}
                  </Button>
                </div>
              </CardHeader>
              {settingsExpanded ? (
                <CardContent className="space-y-4 pt-0">
                  <div className="space-y-2">
                    <Label htmlFor="test-output-dir">Output Directory</Label>
                    <div className="flex gap-2">
                      <Input
                        id="test-output-dir"
                        value={settings.finalOutputDir}
                        onChange={(e) => setSettings((current) => ({ ...current, finalOutputDir: e.target.value }))}
                      />
                      <Button size="icon" variant="outline" onClick={handlePickFolder}>
                        <FolderOpen className="size-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="border-t border-white/10 pt-3 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-amber-300">Tùy chỉnh ảnh layout</div>
                      <div className="flex gap-1 bg-black/40 p-0.5 rounded-lg border border-white/10">
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style1")}
                          className={`text-[11px] px-2 py-0.5 rounded font-medium transition-colors ${
                            settingsStyleTab === "style1" ? "bg-red-600 text-white shadow" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 1 (Đỏ)
                        </button>
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style2")}
                          className={`text-[11px] px-2 py-0.5 rounded font-medium transition-colors ${
                            settingsStyleTab === "style2" ? "bg-emerald-600 text-white shadow" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 2 (Xanh)
                        </button>
                        <button
                          type="button"
                          onClick={() => setSettingsStyleTab("style3")}
                          className={`text-[11px] px-2 py-0.5 rounded font-medium transition-colors ${
                            settingsStyleTab === "style3" ? "bg-pink-600 text-white shadow" : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          Style 3 (Hồng)
                        </button>
                      </div>
                    </div>

                    {settingsStyleTab === "style1" ? (
                      <div className="space-y-3 rounded-xl border border-red-500/20 bg-red-950/10 p-2.5">
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="test-s1-logo" className="text-[11px] text-slate-300">Logo Style 1</Label>
                            {settings.customStyle1LogoPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1LogoPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="test-s1-logo" placeholder="public/logo_tiembachhoa.png" className="text-xs h-8" value={settings.customStyle1LogoPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1LogoPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1LogoPath", "Chọn Logo Style 1")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="test-s1-card-bg" className="text-[11px] text-slate-300">Card BG Style 1</Label>
                            {settings.customStyle1CardBgPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1CardBgPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="test-s1-card-bg" placeholder="public/red-bg.png" className="text-xs h-8" value={settings.customStyle1CardBgPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1CardBgPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1CardBgPath", "Chọn Card BG Style 1")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="test-s1-nhay" className="text-[11px] text-slate-300">Icon Nháy Style 1</Label>
                            {settings.customStyle1NhayPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle1NhayPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="test-s1-nhay" placeholder="public/nhay.png" className="text-xs h-8" value={settings.customStyle1NhayPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle1NhayPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle1NhayPath", "Chọn Icon Nháy Style 1")}>Chọn</Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3 rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-2.5">
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="test-s2-logo" className="text-[11px] text-slate-300">Logo Style 2</Label>
                            {settings.customStyle2LogoPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle2LogoPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="test-s2-logo" placeholder="public/style2/logo.png" className="text-xs h-8" value={settings.customStyle2LogoPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle2LogoPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2LogoPath", "Chọn Logo Style 2")}>Chọn</Button>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="test-s2-card-bg" className="text-[11px] text-slate-300">Card BG Style 2</Label>
                            {settings.customStyle2CardBgPath ? (
                              <button type="button" onClick={() => setSettings(c => ({...c, customStyle2CardBgPath: ''}))} className="text-[10px] text-red-400 hover:underline">Mặc định</button>
                            ) : null}
                          </div>
                          <div className="flex gap-1.5">
                            <Input id="test-s2-card-bg" placeholder="public/style2/green-bg.jpg" className="text-xs h-8" value={settings.customStyle2CardBgPath || ''} onChange={(e) => setSettings((c) => ({ ...c, customStyle2CardBgPath: e.target.value }))} />
                            <Button size="sm" variant="outline" className="h-8 px-2 text-xs" onClick={() => handlePickFile("customStyle2CardBgPath", "Chọn Card BG Style 2")}>Chọn</Button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Button onClick={handleSaveSettings} disabled={savingSettings}>
                      {savingSettings ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />} Lưu
                    </Button>
                    <Button variant="outline" onClick={openOutputFolder}>
                      <FolderOpen className="size-4" /> Mở
                    </Button>
                  </div>
                </CardContent>
              ) : null}
            </Card>
          </aside>

          <section className="space-y-6">
            <Card className="overflow-hidden border-amber-500/30 bg-amber-500/[0.04]">
              <CardHeader>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <CardTitle className="text-amber-200">Cấu hình Test Render</CardTitle>
                    <CardDescription>Nhập URL TikTok và script văn bản để kiểm tra render khung hình 1080x1920.</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Label className="text-sm text-slate-300">Chế độ test:</Label>
                    <Button
                      size="sm"
                      variant={mode === "review" ? "secondary" : "outline"}
                      onClick={() => setMode("review")}
                    >
                      Single Video Review
                    </Button>
                    <Button
                      size="sm"
                      variant={mode === "montage" ? "secondary" : "outline"}
                      onClick={() => setMode("montage")}
                    >
                      Montage Clip
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-3">
                  {rows.map((row, index) => (
                    <div
                      key={row.id}
                      className="grid gap-3 rounded-2xl border border-amber-500/20 bg-white/[0.03] p-4 transition hover:border-amber-400/30 lg:grid-cols-[40px_minmax(0,1fr)_44px]"
                    >
                      <div className="flex size-9 items-center justify-center rounded-xl bg-amber-400/20 text-sm font-semibold text-amber-200">
                        {index + 1}
                      </div>
                      <Input
                        value={row.url}
                        onChange={(e) => updateRow(row.id, { url: e.target.value })}
                        placeholder="Link TikTok video (VD: https://www.tiktok.com/@user/video/123456789)"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeRow(row.id)}
                        disabled={rows.length === 1}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                      <Textarea
                        className="lg:col-start-2 lg:col-end-4"
                        value={row.customScript}
                        onChange={(e) => updateRow(row.id, { customScript: e.target.value })}
                        placeholder="Nhập script văn bản tiếng Việt để test hiển thị ở vùng đỏ bên dưới..."
                      />
                    </div>
                  ))}
                  <div className="flex items-center gap-2 rounded-2xl border border-amber-500/20 bg-white/[0.03] p-4">
                    <Label className="whitespace-nowrap text-xs text-amber-200/60">Tỷ lệ kéo video:</Label>
                    <Input
                      type="number"
                      min="0"
                      max="1"
                      step="0.0001"
                      value={videoShiftRatio}
                      onChange={(e) => setVideoShiftRatio(e.target.value)}
                      className="w-28"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap justify-end gap-3">
                  <Button variant="outline" onClick={addRow}>
                    <Plus className="size-4" /> Thêm đường dẫn test
                  </Button>
                  <Button
                    className="bg-amber-500 font-medium text-black hover:bg-amber-400"
                    onClick={handleTestRender}
                    disabled={submitting}
                  >
                    {submitting ? <LoaderCircle className="size-4 animate-spin" /> : <FlaskConical className="size-4" />} Chạy Test Render (Im lặng)
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>
        </div>
      </div>
    </main>
  );
}
