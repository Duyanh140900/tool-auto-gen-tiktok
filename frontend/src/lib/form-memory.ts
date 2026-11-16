// Ghi nhớ thông số form của lần chạy gần nhất (localStorage của trình duyệt này),
// để lần sau mở trang tự điền lại. Lỗi đọc/ghi (chặn storage, JSON hỏng) thì bỏ qua.

const PREFIX = "tiktok-review-tool:form:";

export function loadFormMemory<T extends object>(key: string): Partial<T> {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? (parsed as Partial<T>) : {};
  } catch {
    return {};
  }
}

export function saveFormMemory<T extends object>(key: string, value: T): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // storage bị chặn / đầy: không ghi nhớ được thì thôi
  }
}
