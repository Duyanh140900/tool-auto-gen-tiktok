#!/usr/bin/env bash
# Đăng nhập TikTok Studio MỘT LẦN trên server không màn hình, qua VNC + SSH tunnel.
# Phiên đăng nhập lưu trong <app>/.tiktok_browser_profile (đừng xóa thư mục này).
#
#   bash deploy/tiktok-login.sh start   # mở Chrome ở trang TikTok Studio + bật VNC (chỉ nghe 127.0.0.1)
#   bash deploy/tiktok-login.sh stop    # đăng nhập xong -> tắt Chrome và VNC (nhả khóa profile)
#
# Sau khi `start`, trên MÁY CỦA BẠN:
#   ssh -L 5901:127.0.0.1:5900 <user>@<server>     (giữ cửa sổ này mở)
#   mở VNC viewer, kết nối 127.0.0.1::5901, nhập mật khẩu VNC mà script in ra.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
PROFILE="$APP_DIR/.tiktok_browser_profile"
PASS_FILE="$HOME/.tiktok_vnc_pass"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

case "${1:-}" in
  start)
    # Chỉ một Chrome được dùng profile một lúc: không mở khi backend đang chạy job.
    if ! curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" | grep -q '"current_job_running":false'; then
      echo "Backend đang chạy job (hoặc không phản hồi). Đợi job xong rồi chạy lại." >&2
      exit 1
    fi
    PW="$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 8)"
    x11vnc -storepasswd "$PW" "$PASS_FILE" >/dev/null 2>&1
    systemd-run --user --unit=tiktok-vnc /usr/bin/x11vnc -display :99 -localhost -rfbport 5900 \
      -rfbauth "$PASS_FILE" -forever -shared >/dev/null
    systemd-run --user --unit=tiktok-login-chrome -E DISPLAY=:99 /usr/bin/google-chrome \
      --user-data-dir="$PROFILE" --lang=en-US --window-position=0,0 --window-size=1400,950 \
      --disable-blink-features=AutomationControlled --no-first-run --no-default-browser-check \
      https://www.tiktok.com/tiktokstudio >/dev/null
    echo "Mật khẩu VNC (tạm thời): $PW"
    echo "Trên máy bạn: ssh -L 5901:127.0.0.1:5900 $USER@<server>  rồi VNC tới 127.0.0.1::5901"
    echo "Đăng nhập xong chạy: bash deploy/tiktok-login.sh stop"
    ;;
  stop)
    systemctl --user stop tiktok-login-chrome tiktok-vnc 2>/dev/null || true
    sleep 3  # để Chrome đóng êm, kịp lưu cookie
    rm -f "$PASS_FILE"
    echo "Đã tắt Chrome đăng nhập và VNC."
    echo "Kiểm tra phiên:  curl -X POST http://127.0.0.1:${BACKEND_PORT}/api/post-schedule/check-studio"
    ;;
  *)
    echo "Cách dùng: bash deploy/tiktok-login.sh {start|stop}" >&2
    exit 2
    ;;
esac
