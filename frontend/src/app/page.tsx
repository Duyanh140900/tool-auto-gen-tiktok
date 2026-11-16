import Link from "next/link";
import { ArrowRight, Layers3, ListVideo, Sparkles, Wand2, Bot, Globe } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function Home() {
  return (
    <main className="min-h-screen py-8 sm:py-10">
      <div className="app-shell flex min-h-[calc(100vh-5rem)] flex-col justify-center gap-8">
        <header className="mx-auto max-w-3xl space-y-5 text-center">
          <div className="mx-auto flex w-fit items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-slate-300 shadow-2xl backdrop-blur">
            <Layers3 className="size-4 text-primary" /> TikTok Review Tool
          </div>
          <div className="space-y-4">
            <h1 className="text-balance text-5xl font-semibold tracking-tight text-white sm:text-6xl">
              Chọn workflow sản xuất video
            </h1>
            <p className="mx-auto max-w-2xl text-pretty text-base leading-7 text-slate-300">
              Hệ thống tự động hóa làm video review & xào video TikTok chuyên nghiệp.
            </p>
          </div>
        </header>

        <section className="mx-auto grid w-full max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {/* Workflow 1: Profile AI Video (New Dedicated Screen) */}
          <Card className="group relative overflow-hidden border-violet-500/50 bg-gradient-to-b from-violet-600/15 via-purple-950/20 to-black/40 p-1 shadow-2xl transition duration-300 hover:-translate-y-1 hover:border-violet-400 hover:bg-violet-600/20">
            <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-br from-violet-500/30 to-fuchsia-500/20 opacity-80 blur-3xl transition group-hover:opacity-100" />
            <div className="relative flex h-full flex-col justify-between rounded-[1.65rem] p-6">
              <CardHeader className="gap-6 p-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex size-14 items-center justify-center rounded-2xl border border-violet-400/40 bg-violet-500/30 shadow-inner">
                    <Globe className="size-7 text-violet-200" />
                  </div>
                  <ArrowRight className="mt-2 size-5 text-violet-400 transition group-hover:translate-x-1 group-hover:text-white" />
                </div>
                <div>
                  <div className="inline-block rounded-full bg-violet-500/30 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-200 mb-2 border border-violet-400/30">
                    Chuyên sâu • Crawl Profile
                  </div>
                  <CardTitle className="text-xl text-white">Profile AI Video</CardTitle>
                  <CardDescription className="mt-2 text-xs leading-5 text-slate-300">
                    Cào toàn bộ link video từ trang cá nhân TikTok, tự động đối chiếu file log JSON để bỏ qua video đã làm, tỷ lệ kéo mặc định 0.25.
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="p-0 pt-6">
                <Button asChild className="w-full justify-between bg-violet-600 hover:bg-violet-500 text-white font-semibold">
                  <Link href="/profile-ai-video">
                    Mở Profile AI <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </CardContent>
            </div>
          </Card>

          {/* Workflow 2: AI TikTok Video (Single / Multi Link) */}
          <Card className="group relative overflow-hidden border-violet-500/40 bg-gradient-to-b from-violet-600/10 to-violet-950/20 p-1 shadow-2xl transition duration-300 hover:-translate-y-1 hover:border-violet-400 hover:bg-violet-600/15">
            <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-br from-violet-500/30 to-fuchsia-500/20 opacity-80 blur-3xl transition group-hover:opacity-100" />
            <div className="relative flex h-full flex-col justify-between rounded-[1.65rem] p-6">
              <CardHeader className="gap-6 p-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex size-14 items-center justify-center rounded-2xl border border-violet-400/30 bg-violet-500/20 shadow-inner">
                    <Bot className="size-7 text-violet-300" />
                  </div>
                  <ArrowRight className="mt-2 size-5 text-violet-400 transition group-hover:translate-x-1 group-hover:text-white" />
                </div>
                <div>
                  <div className="inline-block rounded-full bg-violet-500/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-300 mb-2">
                    9Router AI • Review
                  </div>
                  <CardTitle className="text-xl text-white">AI TikTok Video</CardTitle>
                  <CardDescription className="mt-2 text-xs leading-5 text-slate-300">
                    Chỉ cần dán link: AI tự động phân tích giỏ hàng, viết script có emotion tags, zoom video và xuất tên file Caption + Hashtag.
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="p-0 pt-6">
                <Button asChild className="w-full justify-between bg-white/10 hover:bg-white/20 text-white">
                  <Link href="/ai-video">
                    Mở AI Video <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </CardContent>
            </div>
          </Card>

          {/* Workflow 3: Xào video */}
          <Card className="group relative overflow-hidden border-white/10 bg-white/[0.045] p-1 shadow-2xl transition duration-300 hover:-translate-y-1 hover:border-white/20 hover:bg-white/[0.07]">
            <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-br from-fuchsia-400/20 to-sky-300/10 opacity-80 blur-3xl transition group-hover:opacity-100" />
            <div className="relative flex h-full flex-col justify-between rounded-[1.65rem] p-6">
              <CardHeader className="gap-6 p-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex size-14 items-center justify-center rounded-2xl border border-white/10 bg-white/10 shadow-inner">
                    <Sparkles className="size-7 text-fuchsia-200" />
                  </div>
                  <ArrowRight className="mt-2 size-5 text-slate-500 transition group-hover:translate-x-1 group-hover:text-white" />
                </div>
                <div>
                  <CardTitle className="text-xl text-white">Xào video</CardTitle>
                  <CardDescription className="mt-2 text-xs leading-5 text-slate-300">
                    Cắt ghép nhiều video TikTok thành một video dọc 9:16 đồng bộ với voice-over TTS.
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="p-0 pt-6">
                <Button asChild className="w-full justify-between">
                  <Link href="/montage">
                    Mở Xào video <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </CardContent>
            </div>
          </Card>
        </section>

        <footer className="text-center text-sm text-slate-500">Chạy nội bộ trên localhost • FastAPI + Next.js</footer>
      </div>
    </main>
  );
}
