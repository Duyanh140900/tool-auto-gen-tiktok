# TikTok Review & Video Automation Tool 🎬

Hệ thống tự động và bán tự động tạo video review chuẩn định dạng TikTok 9:16:

- **Tự động tải video TikTok không logo/watermark** (hỗ trợ cả `yt-dlp` và fallback `TikWM API`).
- **Nhận diện sản phẩm & sinh kịch bản AI** bằng LLM (hỗ trợ **9Router Proxy**, **OpenAI**, **Claude**), tự động sinh tiêu đề Banner Title giật gân (20–30 từ) và kịch bản voice-over (60–80 từ) kèm các tag cảm xúc ElevenLabs v3 (`[gasps]`, `[excited]`, `[whispers]`, `[laughs]`,...).
- **Đọc giọng thuyết minh chuyên nghiệp** qua API **Itera102** (ElevenLabs engine) hoặc **Microsoft Edge TTS** (miễn phí).
- **Ghép layout và render video 9:16 chất lượng cao** bằng FFmpeg: nửa trên phát video sản phẩm (chỉnh được zoom/scale và tỷ lệ dịch khung hình), nửa dưới hiển thị thẻ banner bo góc cùng logo và icon giỏ hàng.
- **Đặt tên file thông minh**: lưu dạng `<Caption_sản_phẩm>_<Hashtags>.mp4`.
- **Tự đăng hẹn giờ lên TikTok Studio** (Playwright + Chrome), gắn giỏ hàng sản phẩm của video nguồn; lịch cố định 08:00, 12:00, 18:00, 22:00 hoặc giờ/ngày tùy chọn cho từng video.
- **Bot Telegram**: gửi link vào chat → tool tự chạy cả quy trình.

---

## 📋 Mục lục

1. [Yêu cầu hệ thống](#-yêu-cầu-hệ-thống)
2. [Cài đặt trên Windows](#-cài-đặt-trên-windows)
3. [Cấu hình `.env`](#-cấu-hình-env)
4. [Khởi chạy & các luồng xử lý](#-khởi-chạy--các-luồng-xử-lý)
5. [Bot Telegram](#-bot-telegram)
6. [Cài đặt trên server Ubuntu](#-cài-đặt-trên-server-ubuntu)
7. [Đăng nhập TikTok Studio (đăng hẹn giờ)](#-đăng-nhập-tiktok-studio-đăng-hẹn-giờ)
8. [Vận hành & cập nhật](#-vận-hành--cập-nhật)
9. [Bảo mật](#-bảo-mật)
10. [Đóng gói file ZIP](#-đóng-gói-file-zip)

---

## 📋 Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| Python | 3.10 trở lên (khuyến nghị 3.12) |
| Node.js | **20 trở lên** (khuyến nghị 22). Node 18 **không** build được frontend (Tailwind 4 / Next 15). |
| FFmpeg | Có trong `PATH` (`ffmpeg -version`). Windows: `winget install Gyan.FFmpeg` |
| Chrome | Chỉ cần nếu dùng đăng hẹn giờ TikTok Studio |

---

## 🚀 Cài đặt trên Windows

```cmd
git clone https://github.com/Duyanh140900/tool-auto-gen-tiktok.git
cd tool-auto-gen-tiktok
scripts\dev_all.cmd install
copy .env.example .env
```

`scripts\dev_all.cmd install` cài Python dependencies (`requirements.txt`) và `npm install` cho `frontend/`.
Cài thủ công: `python -m pip install -r requirements.txt` rồi `cd frontend && npm install`.

Sau đó mở `.env` và điền key (xem mục tiếp theo).

---

## ⚙️ Cấu hình `.env`

`.env` chứa khóa API nên **không bao giờ commit** (đã nằm trong `.gitignore`). Mẫu đầy đủ ở `.env.example`.

**TTS – Itera102 (ElevenLabs):**
```env
ITERA102_API_KEY=sk_your_itera102_api_key_here
ITERA102_VOICE_ID=pNInz6obpgDQGcFmaJgB
ITERA102_BASE_URL=https://api.itera102.space
ITERA102_MODEL_ID=eleven_v3
ITERA102_LANGUAGE_CODE=vi
```
Chưa có key Itera102 thì dùng Edge TTS miễn phí (`EDGE_TTS_VOICE=vi-VN-NamMinhNeural`).

**LLM sinh kịch bản** (chọn 1 trong 3):
```env
# 9Router chạy cục bộ (khuyến nghị)
LLM_PROVIDER=openai
LLM_API_KEY=sk-your_9router_key_here
LLM_BASE_URL=http://localhost:20128/v1
LLM_MODEL=your_model_name

# hoặc OpenAI trực tiếp
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-proj-xxxxxxxx
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL=gpt-4o-mini

# hoặc Claude (Anthropic)
# LLM_PROVIDER=anthropic
# LLM_API_KEY=sk-ant-api03-xxxxxxxx
# LLM_MODEL=<tên model Claude>
```

**Thư mục lưu video (tùy chọn):** mặc định `~/tiktok-review-tool/`. Đổi bằng `FINAL_OUTPUT_DIR` (Windows: `D:/TikTokVideos/Output`, Linux: `/home/<user>/tiktok-videos`).

**Tùy chọn khác:** `TIKTOK_COOKIES_FILE` (cookies.txt khi video bị chặn vùng), `POST_SCHEDULE_MAX_DAYS`, `POST_DELAY_SECONDS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` – xem chú thích trong `.env.example`.

---

## 💻 Khởi chạy & các luồng xử lý

```cmd
scripts\dev_all.cmd
```

Khởi động **FastAPI backend** tại `http://127.0.0.1:8000` và **Next.js UI** tại `http://127.0.0.1:3000` (tiến độ cập nhật realtime qua WebSocket). Dừng bằng `scripts\dev_all.cmd stop`.

Các chế độ trên Web UI:

1. **Auto Video AI (`/ai-video`) – khuyến nghị**: dán danh sách link TikTok → tải video, LLM nhận diện sản phẩm và viết kịch bản, TTS tạo giọng đọc, render 9:16, đặt tên `<Caption>_<Hashtags>.mp4`. Có thanh chỉnh **Tỷ lệ kéo video (Y-offset)** và **Scale**.
2. **Auto Gen Video (`/auto-gen-video`)**: nhập link kèm sản phẩm/kịch bản tùy chỉnh.
3. **Xào Video TikTok (`/montage`)**: ghép nhiều clip nguồn thành một video.
4. **Profile AI Video (`/profile-ai-video`)**: quét video từ một profile TikTok rồi chạy hàng loạt.
5. **Test Render (`/test-render`)**: xem trước layout 5 giây, không tốn quota API.

---

## 🤖 Bot Telegram

Điền `TELEGRAM_BOT_TOKEN` (tạo bot với @BotFather) vào `.env` và khởi động lại backend. Lần đầu nhắn bot, bot trả **Chat ID** → điền vào `TELEGRAM_ALLOWED_CHAT_IDS` (nhiều ID cách nhau dấu phẩy) rồi khởi động lại.

Bot dùng đúng setting đang chọn ở trang `/ai-video`. Mỗi dòng 1 link, có thể ghi kèm (đều tùy chọn):

```
link - chủ đề - Y-offset - scale - giờ - ngày
https://vt.tiktok.com/abc/ - Black Friday - 0.4 - 1.1 - 18:30 - 20/11
```

| Phần | Định dạng | Nếu bỏ trống |
|---|---|---|
| Chủ đề | chữ tự do | theo `/settings` |
| Y-offset (tỷ lệ kéo video) | số 0–1 | theo `/settings` |
| Scale | số 0.1–3 | theo `/settings` |
| Giờ | `18:30`, `18h30`, `18h` (phút làm tròn xuống bội số 5) | slot tự động |
| Ngày | `20/11` hoặc `20/11/2026` | slot tự động |

- Số thuần xếp theo vị trí: **một số = Y-offset**, hai số = Y-offset rồi scale. Dùng `_` để bỏ qua một ô (vd `_ - 1.2` chỉ đặt scale).
- Chỉ có giờ → hôm nay (qua giờ rồi thì ngày mai); chỉ có ngày → 08:00. Giờ/ngày giờ chỉ có tác dụng khi bật **Đăng hẹn giờ** trong `/settings`.
- Giờ đã qua / cách hiện tại dưới 15 phút → bài đó báo lỗi và video được giữ lại. Giờ quá `POST_SCHEDULE_MAX_DAYS` (mặc định 30) ngày → vào hàng chờ.

Lệnh: `/help` `/settings` `/status` `/queue` `/clear` `/cancel`.

---

## 🐧 Cài đặt trên server Ubuntu

Đã thử với Ubuntu 24.04. Toàn bộ quy trình (tải → LLM → TTS → render → đăng hẹn giờ) chạy được trên server không màn hình; Chrome chạy trong màn hình ảo Xvfb.

> **Không dùng** được trên server: nút chọn thư mục/file và nút mở thư mục trên giao diện (cần hộp thoại hệ điều hành), và tính năng *Showcase* (cần điện thoại Android cắm USB/ADB).

### Cài tự động

```bash
git clone https://github.com/Duyanh140900/tool-auto-gen-tiktok.git
cd tool-auto-gen-tiktok
bash deploy/install-ubuntu.sh
```

Chạy bằng user thường, script sẽ gọi `sudo` cho `apt` và `loginctl enable-linger`. Script thực hiện:

1. Cài `ffmpeg`, `xvfb`, `x11vnc`, `python3-venv`, font DejaVu...
2. Cài Google Chrome (nếu chưa có).
3. Cài Node.js 22 vào `~/node22` nếu Node hệ thống < 20 (kiểm tra SHA-256).
4. Tạo `.venv`, cài `requirements-server.txt` (bản rút gọn: bỏ `PyQt6`, `pyautogui`, `pyobjc` vì chỉ dùng cho app desktop).
5. Tạo `.env` từ `.env.example`, đặt `FINAL_OUTPUT_DIR=~/tiktok-videos`.
6. Build frontend.
7. Tạo 3 service `systemd --user`: `tiktok-xvfb`, `tiktok-backend`, `tiktok-frontend` (tự chạy khi khởi động máy).
8. Bật linger để service chạy khi không có phiên SSH.

Tùy chỉnh bằng biến môi trường:

```bash
FRONTEND_PORT=3100 BIND_HOST=0.0.0.0 APP_TZ=Asia/Ho_Chi_Minh bash deploy/install-ubuntu.sh
```

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `FRONTEND_PORT` | 3000 | Cổng giao diện web (đổi nếu bị chiếm) |
| `BACKEND_PORT` | 8000 | Cổng FastAPI (chỉ nghe `127.0.0.1`) |
| `BIND_HOST` | 127.0.0.1 | `0.0.0.0` để cả mạng LAN truy cập (xem phần [Bảo mật](#-bảo-mật)) |
| `APP_TZ` | Asia/Ho_Chi_Minh | Múi giờ backend/Chrome. **Quan trọng**: server thường chạy UTC, nếu sai múi giờ thì giờ hẹn đăng lệch (vd 08:00 thành 15:00 giờ VN). |

Sau khi cài xong, **mở `.env` điền API key** rồi `systemctl --user restart tiktok-backend`. Giao diện: `http://<server>:<FRONTEND_PORT>/ai-video` (hoặc dùng SSH tunnel: `ssh -L 3000:127.0.0.1:3000 user@server`).

### Cài thủ công (nếu không dùng script)

```bash
sudo apt install -y ffmpeg xvfb x11vnc python3-venv python3-pip fonts-dejavu-core wget curl
# Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo apt install -y ./google-chrome-stable_current_amd64.deb
# Node >= 20 (Node 18 của Ubuntu không build được frontend) – ví dụ cài vào ~/node22 từ nodejs.org

python3 -m venv .venv && .venv/bin/pip install -r requirements-server.txt
cp .env.example .env            # rồi điền key
cd frontend && npm install && npm run build && cd ..

# Chạy (cần màn hình ảo cho Chrome đăng bài)
Xvfb :99 -screen 0 1440x1000x24 -nolisten tcp &
DISPLAY=:99 TZ=Asia/Ho_Chi_Minh .venv/bin/python -m uvicorn src.web.app:app --host 127.0.0.1 --port 8000 &
cd frontend && npm run start -- -p 3000
```

Mẫu service nằm trong `deploy/systemd/`.

---

## 🔐 Đăng nhập TikTok Studio (đăng hẹn giờ)

Lần đầu phải đăng nhập tay một lần; phiên lưu trong `.tiktok_browser_profile/` (**đừng xóa**, đừng commit). Trên server không có màn hình, dùng VNC qua SSH tunnel:

```bash
# Trên server (đợi job đang chạy xong; chỉ 1 Chrome được dùng profile một lúc)
bash deploy/tiktok-login.sh start        # in ra mật khẩu VNC tạm thời
```

```bash
# Trên máy của bạn (giữ cửa sổ này mở)
ssh -L 5901:127.0.0.1:5900 user@server
```

Mở VNC viewer (TightVNC Viewer, RealVNC Viewer...) → kết nối `127.0.0.1::5901` → nhập mật khẩu VNC → đăng nhập TikTok Studio trong cửa sổ Chrome (giao diện tiếng Anh; tự xử lý captcha nếu có). Xong:

```bash
bash deploy/tiktok-login.sh stop
curl -X POST http://127.0.0.1:8000/api/post-schedule/check-studio   # kiểm tra phiên, chỉ đọc màn Posts
```

Lưu ý: IP datacenter dễ bị TikTok bắt xác minh/captcha, và tool không tự giải captcha. Nếu hết phiên, làm lại các bước trên. Selector của TikTok Studio có thể hỏng khi TikTok đổi giao diện.

---

## 🛠 Vận hành & cập nhật

```bash
systemctl --user status tiktok-backend tiktok-frontend tiktok-xvfb
systemctl --user restart tiktok-backend           # sau khi sửa .env hoặc cập nhật code
journalctl --user -u tiktok-backend -f            # xem log
curl http://127.0.0.1:8000/api/health             # "current_job_running": false = rảnh
```

Cập nhật phiên bản mới:

```bash
git pull
.venv/bin/pip install -r requirements-server.txt
cd frontend && npm install && npm run build && cd ..
systemctl --user restart tiktok-backend tiktok-frontend
```

> **Chỉ khởi động lại khi không có job đang chạy** (kiểm tra `/api/health`): job chạy trong bộ nhớ nên sẽ dừng giữa chừng nếu restart.

Dữ liệu cần giữ khi chuyển máy: `.env`, `.tiktok_browser_profile/`, `.ai_video_defaults.json` (setting đã lưu), `<FINAL_OUTPUT_DIR>/post_schedule.json` (sổ lịch đăng).

Video đăng xong được chuyển vào **Thùng rác** (`~/.local/share/Trash`) nếu bật tùy chọn xóa sau khi hẹn; tool không tự dọn thùng rác nên hãy dọn định kỳ.

---

## 🔒 Bảo mật

- **Giao diện web và API không có đăng nhập.** Ai truy cập được cổng giao diện đều tạo được job và dùng API key trong `.env`. Mặc định script chỉ nghe `127.0.0.1`; nếu đặt `BIND_HOST=0.0.0.0` hãy giới hạn bằng tường lửa/VPN hoặc reverse proxy có xác thực.
- `.env`, `cookies.txt`, `.tiktok_browser_profile/`, `.ai_video_defaults.json` chứa khóa/phiên đăng nhập – đã nằm trong `.gitignore`, **không commit, không gửi cho người khác**.
- Nếu lỡ lộ khóa API (dán vào chat, commit nhầm...) hãy thu hồi và tạo khóa mới.
- Bot Telegram chỉ nhận lệnh từ `TELEGRAM_ALLOWED_CHAT_IDS`.

---

## 📦 Đóng gói file ZIP

Để gửi dự án cho người khác:

1. Xóa file nhạy cảm và tạm: `.env`, `cookies.txt`, `.tiktok_browser_profile/`, `.ai_video_defaults.json`, `frontend/.next`, `frontend/node_modules`, `__pycache__`, `.pytest_cache`, `outputs/`.
2. Nén thành `tiktok-review-tool.zip` (hoặc chạy `python scripts/build_zip.py`).
3. Người nhận: giải nén → `scripts\dev_all.cmd install` → `copy .env.example .env` và điền key → `scripts\dev_all.cmd`.
