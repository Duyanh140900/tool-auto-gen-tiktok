#!/usr/bin/env bash
# Cài đặt TikTok Review Tool trên Ubuntu 22.04 / 24.04.
#
# Chạy bằng user thường (KHÔNG chạy bằng root); cần quyền sudo cho apt và lệnh linger.
#   bash deploy/install-ubuntu.sh
#
# Biến môi trường tùy chọn:
#   FRONTEND_PORT   cổng giao diện web            (mặc định 3000)
#   BACKEND_PORT    cổng FastAPI, chỉ nghe nội bộ (mặc định 8000)
#   BIND_HOST       địa chỉ giao diện web nghe    (mặc định 127.0.0.1; đặt 0.0.0.0 để cả mạng LAN vào được)
#   APP_TZ          múi giờ cho backend/Chrome    (mặc định Asia/Ho_Chi_Minh; ảnh hưởng giờ hẹn đăng)
#
# CẢNH BÁO: giao diện web không có đăng nhập. Chỉ đặt BIND_HOST=0.0.0.0 trong mạng tin cậy,
# hoặc đặt sau reverse proxy có xác thực.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
APP_TZ="${APP_TZ:-Asia/Ho_Chi_Minh}"
NODE_MIN_MAJOR=20

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mLỗi: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Đừng chạy bằng root. Hãy chạy bằng user thường (script sẽ gọi sudo khi cần)."
command -v sudo >/dev/null || die "Cần sudo."
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || echo "Cảnh báo: script được viết cho Ubuntu, hệ thống hiện tại là ${PRETTY_NAME:-không rõ}."

log "1/8 Cài gói hệ thống (ffmpeg, Xvfb, x11vnc, Python venv, font...)"
sudo apt-get update
sudo apt-get install -y ffmpeg xvfb x11vnc python3 python3-venv python3-pip \
  fonts-dejavu-core wget curl ca-certificates xz-utils

log "2/8 Google Chrome (dùng cho đăng hẹn giờ TikTok Studio)"
if ! command -v google-chrome >/dev/null; then
  wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/google-chrome.deb
  sudo apt-get install -y /tmp/google-chrome.deb
  rm -f /tmp/google-chrome.deb
else
  echo "Đã có: $(google-chrome --version)"
fi

log "3/8 Node.js >= ${NODE_MIN_MAJOR}"
NODE_BIN=""
if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge "$NODE_MIN_MAJOR" ]; then
  NODE_BIN="$(dirname "$(command -v node)")"
  echo "Dùng Node có sẵn: $(node --version)"
else
  NODE_BIN="$HOME/node22/bin"
  if [ ! -x "$NODE_BIN/node" ]; then
    # Node của Ubuntu (18.x) quá cũ cho Tailwind 4 / Next 15 -> cài Node 22 bản chính thức vào $HOME/node22
    cd /tmp
    NODE_TAR="$(curl -fsS https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep -o 'node-v22[0-9.]*-linux-x64.tar.xz' | head -1)"
    [ -n "$NODE_TAR" ] || die "Không lấy được bản Node 22 từ nodejs.org"
    curl -fsS -O "https://nodejs.org/dist/latest-v22.x/$NODE_TAR"
    curl -fsS https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep " $NODE_TAR\$" | sha256sum -c -
    mkdir -p "$HOME/node22"
    tar xJf "$NODE_TAR" -C "$HOME/node22" --strip-components=1
    rm -f "$NODE_TAR"
  fi
  echo "Node: $("$NODE_BIN/node" --version) ($NODE_BIN)"
fi
export PATH="$NODE_BIN:$PATH"

log "4/8 Python venv + thư viện"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-server.txt

log "5/8 File cấu hình .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Đã tạo .env từ .env.example -> HÃY MỞ .env VÀ ĐIỀN API KEY (LLM_API_KEY, ITERA102_API_KEY...)."
fi
chmod 600 .env
if ! grep -qE '^FINAL_OUTPUT_DIR=' .env; then
  echo "FINAL_OUTPUT_DIR=$HOME/tiktok-videos" >> .env
  echo "Đã đặt FINAL_OUTPUT_DIR=$HOME/tiktok-videos"
fi
mkdir -p "$HOME/tiktok-videos"

log "6/8 Build frontend"
cd "$APP_DIR/frontend"
export NEXT_PUBLIC_API_TARGET="http://127.0.0.1:${BACKEND_PORT}" NEXT_TELEMETRY_DISABLED=1
npm install --no-audit --no-fund
npm run build

log "7/8 Tạo service systemd (user): xvfb, backend, frontend"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR" "$APP_DIR/logs"
for unit in tiktok-xvfb tiktok-backend tiktok-frontend; do
  sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@NODE_BIN@|$NODE_BIN|g" \
      -e "s|@FRONTEND_PORT@|$FRONTEND_PORT|g" -e "s|@BACKEND_PORT@|$BACKEND_PORT|g" \
      -e "s|@BIND_HOST@|$BIND_HOST|g" -e "s|@APP_TZ@|$APP_TZ|g" \
      "$APP_DIR/deploy/systemd/$unit.service" > "$UNIT_DIR/$unit.service"
done
systemctl --user daemon-reload
systemctl --user enable --now tiktok-xvfb tiktok-backend tiktok-frontend

log "8/8 Cho service chạy khi không có phiên đăng nhập (linger)"
sudo loginctl enable-linger "$USER"

sleep 6
echo
systemctl --user is-active tiktok-xvfb tiktok-backend tiktok-frontend || true
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" && echo
cat <<EOF

Xong. Giao diện: http://${BIND_HOST}:${FRONTEND_PORT}/ai-video
Việc còn lại:
  1. Điền API key trong $APP_DIR/.env rồi chạy:  systemctl --user restart tiktok-backend
  2. Đăng nhập TikTok Studio một lần (nếu dùng đăng hẹn giờ):  bash deploy/tiktok-login.sh start
  Xem hướng dẫn chi tiết trong README.md (mục "Cài đặt trên server Ubuntu").
EOF
