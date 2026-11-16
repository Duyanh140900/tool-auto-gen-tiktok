"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, LoaderCircle, ShoppingBag, Smartphone } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type PostScheduleSummary, type PostState, type ShowcaseState } from "@/lib/api";
import { toast } from "@/hooks/use-toast";

// Tùy chọn tự thêm sản phẩm của video nguồn vào Showcase sau khi gen xong video.
export function ShowcaseOptions({
  enabled,
  dry,
  onEnabledChange,
  onDryChange,
  disabled,
}: {
  enabled: boolean;
  dry: boolean;
  onEnabledChange: (value: boolean) => void;
  onDryChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  const [checking, setChecking] = useState(false);

  async function checkDevice() {
    setChecking(true);
    try {
      const res = await api.checkShowcaseDevice();
      toast({
        title: res.ok ? "Điện thoại sẵn sàng" : "Chưa kết nối được điện thoại",
        description: res.ok ? `${res.model ?? res.serial ?? "Android"} · ${res.package}` : res.error,
        variant: res.ok ? "default" : "destructive",
      });
    } catch (error) {
      toast({
        title: "Không kiểm tra được điện thoại",
        description: error instanceof Error ? error.message : String(error),
        variant: "destructive",
      });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-4 text-xs">
      <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onEnabledChange(e.target.checked)}
          className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
          disabled={disabled}
        />
        <ShoppingBag className="h-3.5 w-3.5" />
        <span>Gen xong tự thêm sản phẩm vào Showcase</span>
      </label>
      {enabled ? (
        <>
          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
            <input
              type="checkbox"
              checked={dry}
              onChange={(e) => onDryChange(e.target.checked)}
              className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
              disabled={disabled}
            />
            <span>Chạy thử (không bấm nút thêm)</span>
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
            onClick={checkDevice}
            disabled={checking}
          >
            {checking ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Smartphone className="h-3.5 w-3.5" />}
            Kiểm tra điện thoại
          </Button>
        </>
      ) : null}
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  queued: "Chờ Showcase",
  running: "Đang thêm Showcase",
  done: "Đã thêm Showcase",
  error: "Lỗi Showcase",
  cancelled: "Bỏ qua Showcase",
};

const PRODUCT_STATUS_LABEL: Record<string, string> = {
  thanh_cong: "đã thêm",
  da_co: "đã có sẵn",
  thu: "chạy thử",
  loi: "lỗi",
};

export function ShowcaseBadge({ showcase }: { showcase?: ShowcaseState | null }) {
  if (!showcase) return null;
  const variant =
    showcase.status === "done" ? "success" : showcase.status === "error" ? "destructive" : "secondary";
  const label = `${STATUS_LABEL[showcase.status] ?? showcase.status}${showcase.dry ? " (thử)" : ""}`;
  const detail = showcase.results.length
    ? showcase.results
        .map((r) => `${r.product || "Sản phẩm"}: ${PRODUCT_STATUS_LABEL[r.status] ?? r.status}${r.note ? ` – ${r.note}` : ""}`)
        .join("\n")
    : showcase.message;
  return (
    <Badge variant={variant} className="mt-1 text-[11px] gap-1" title={detail}>
      {showcase.status === "running" ? (
        <LoaderCircle className="h-3 w-3 animate-spin" />
      ) : (
        <ShoppingBag className="h-3 w-3" />
      )}
      {label}
    </Badge>
  );
}

function formatSlot(slot?: string | null) {
  if (!slot) return "—";
  const d = new Date(slot);
  if (Number.isNaN(d.getTime())) return slot;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`;
}

// Đăng hẹn giờ TikTok Studio sau bước Showcase: 4 video/ngày lúc 8h, 12h, 18h, 22h.
export function PostOptions({
  enabled,
  dry,
  deleteAfter,
  onEnabledChange,
  onDryChange,
  onDeleteAfterChange,
  disabled,
  refreshKey,
}: {
  enabled: boolean;
  dry: boolean;
  deleteAfter: boolean;
  onEnabledChange: (value: boolean) => void;
  onDryChange: (value: boolean) => void;
  onDeleteAfterChange: (value: boolean) => void;
  disabled?: boolean;
  refreshKey?: unknown; // đổi giá trị (vd trạng thái job) để tải lại mốc lịch
}) {
  const [summary, setSummary] = useState<PostScheduleSummary | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.getPostSchedule();
      setSummary(res);
    } catch {
      setSummary(null);
    }
  }, []);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load, refreshKey]);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      toast({ title: success });
      await load();
    } catch (error) {
      toast({
        title: "Không thực hiện được",
        description: error instanceof Error ? error.message : String(error),
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onEnabledChange(e.target.checked)}
            className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
            disabled={disabled}
          />
          <CalendarClock className="h-3.5 w-3.5" />
          <span>Đăng hẹn giờ TikTok Studio + gắn giỏ hàng (8h · 12h · 18h · 22h)</span>
        </label>
        {enabled ? (
          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
            <input
              type="checkbox"
              checked={dry}
              onChange={(e) => onDryChange(e.target.checked)}
              className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
              disabled={disabled}
            />
            <span>Chạy thử (điền đủ, không bấm Lên lịch)</span>
          </label>
        ) : null}
        {enabled ? (
          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white">
            <input
              type="checkbox"
              checked={deleteAfter}
              onChange={(e) => onDeleteAfterChange(e.target.checked)}
              className="rounded border-white/20 bg-black/40 text-violet-600 focus:ring-violet-500"
              disabled={disabled}
            />
            <span>Hẹn xong thì xóa video (vào Thùng rác)</span>
          </label>
        ) : null}
      </div>
      {enabled ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-slate-400">
          <span>
            Đã hẹn đến: <b className="text-slate-200">{formatSlot(summary?.last_slot)}</b>
          </span>
          <span>
            Slot tiếp: <b className="text-violet-300">{formatSlot(summary?.next_slot)}</b>
          </span>
          <span>Hàng chờ: {summary?.waiting_count ?? 0}</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
            disabled={busy || disabled || summary?.flush_running}
            onClick={() => run(() => api.checkPostStudio(), "Đã đọc lịch từ TikTok Studio")}
          >
            {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
            Kiểm tra TikTok Studio
          </Button>
          {summary?.backlog_count ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
              disabled={busy || disabled}
              onClick={() =>
                run(
                  () => api.postBacklog({ post_dry: dry, post_delete_after: deleteAfter }),
                  "Đang lên lịch video đã tạo, theo dõi ở bảng tiến độ",
                )
              }
            >
              Lên lịch {summary.backlog_count} video đã tạo
            </Button>
          ) : null}
          {summary?.waiting_count ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-violet-400 hover:text-violet-300"
              disabled={busy || disabled || summary.flush_running}
              onClick={() => run(() => api.flushPostSchedule(), "Đang đăng hàng chờ trên cửa sổ Chrome")}
            >
              {summary.flush_running ? "Đang đăng hàng chờ…" : "Đăng hàng chờ"}
            </Button>
          ) : null}
          <span className="w-full text-[10px] text-slate-500">
            Mỗi lần chạy, tool đọc màn Posts của TikTok Studio để biết đang hẹn đến đâu
            {summary?.studio_checked_at ? ` (lần đọc gần nhất ${formatSlot(summary.studio_checked_at)})` : ""}. Không cần bật Showcase:
            tool đọc sản phẩm gắn trong video nguồn (nhiều sản phẩm thì 9router chọn theo tên sản phẩm của video); tên giỏ hàng ~2 từ do 9router đặt. TikTok chỉ hẹn trước tối đa{" "}
            {summary?.max_days_ahead ?? 30} ngày, quá hạn thì vào hàng chờ. Đóng mọi cửa sổ Chrome của tool trước khi chạy.
          </span>
        </div>
      ) : null}
    </div>
  );
}

const POST_STATUS_LABEL: Record<string, string> = {
  queued: "Chờ đăng",
  running: "Đang đăng",
  scheduled: "Đã hẹn",
  unverified: "Chưa xác nhận",
  waiting: "Hàng chờ",
  thu: "Đăng thử",
  error: "Lỗi đăng",
  cancelled: "Bỏ qua đăng",
};

export function PostBadge({ post }: { post?: PostState | null }) {
  if (!post) return null;
  const variant =
    post.status === "scheduled" ? "success" : post.status === "error" ? "destructive" : post.status === "waiting" || post.status === "unverified" ? "warning" : "secondary";
  const slot = post.slot && post.status !== "error" ? ` ${formatSlot(post.slot)}` : "";
  const detail = [post.short_name && `Giỏ hàng: ${post.short_name}`, post.product && `Sản phẩm: ${post.product}`, post.message]
    .filter(Boolean)
    .join("\n");
  return (
    <Badge variant={variant} className="mt-1 text-[11px] gap-1" title={detail}>
      {post.status === "running" ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <CalendarClock className="h-3 w-3" />}
      {POST_STATUS_LABEL[post.status] ?? post.status}
      {slot}
    </Badge>
  );
}
