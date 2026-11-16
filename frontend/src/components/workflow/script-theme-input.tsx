"use client";

import { Input } from "@/components/ui/input";

// Gợi ý chủ đề theo các ngày lễ / dịp mua sắm trong năm. Người dùng vẫn gõ tự do được.
export const SCRIPT_THEME_SUGGESTIONS: string[] = [
  "Tết Dương lịch 1/1 - năm mới, đặt mục tiêu, dọn dẹp đón năm mới",
  "Tết Nguyên Đán - sắm Tết, dọn nhà, về quê sum họp, quà biếu",
  "Valentine 14/2 - quà cho người yêu, hẹn hò",
  "Quốc tế Phụ nữ 8/3 - quà tặng mẹ, vợ, bạn gái, đồng nghiệp nữ",
  "Cá tháng Tư 1/4 - troll vui, sự thật bất ngờ",
  "Giỗ Tổ Hùng Vương 10/3 âm lịch - kỳ nghỉ ngắn",
  "Lễ 30/4 - 1/5 - nghỉ dài, du lịch, đi chơi xa",
  "Ngày của Mẹ - quà tặng mẹ, chăm sóc mẹ",
  "Quốc tế Thiếu nhi 1/6 - quà cho bé, đồ cho con",
  "Ngày của Cha - quà tặng bố",
  "Ngày Gia đình Việt Nam 28/6 - gắn kết gia đình",
  "Mùa hè - nắng nóng, đi biển, nghỉ hè",
  "Lễ Vu Lan - báo hiếu cha mẹ",
  "Mùa tựu trường - đồ dùng học tập, sinh viên ở trọ",
  "Quốc khánh 2/9 - nghỉ lễ, du lịch",
  "Tết Trung thu - đoàn viên, quà biếu, rước đèn cho bé",
  "Phụ nữ Việt Nam 20/10 - quà tặng phái đẹp",
  "Halloween 31/10 - hóa trang, rùng rợn mà hài",
  "Ngày độc thân 11/11 - sale lớn, tự thưởng cho bản thân",
  "Nhà giáo Việt Nam 20/11 - tri ân thầy cô",
  "Black Friday - săn sale giá sốc",
  "Sale 12/12 - chốt đơn cuối năm",
  "Giáng sinh - quà Noel, trang trí, tiệc cuối năm",
  "Tất niên cuối năm - tổng kết năm, chuẩn bị Tết",
];

type ScriptThemeInputProps = {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
};

export function ScriptThemeInput({ id = "script-theme", value, onChange, disabled }: ScriptThemeInputProps) {
  const listId = `${id}-suggestions`;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-xs font-medium text-slate-300">
          Chủ đề kịch bản (tùy chọn)
        </label>
        {value.trim() ? (
          <button
            type="button"
            onClick={() => onChange("")}
            disabled={disabled}
            className="text-[11px] text-violet-300 hover:text-violet-200 disabled:opacity-50"
          >
            Xóa chủ đề
          </button>
        ) : null}
      </div>
      <Input
        id={id}
        list={listId}
        value={value}
        maxLength={300}
        onChange={(e) => onChange(e.target.value)}
        className="bg-black/30 border-white/10 text-xs"
        placeholder="Để trống = AI tự chọn. Ví dụ: Tết Trung thu, 20/10, Black Friday, mùa tựu trường..."
        disabled={disabled}
      />
      <datalist id={listId}>
        {SCRIPT_THEME_SUGGESTIONS.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <p className="text-[10px] text-slate-400">
        Nhập chủ đề (ví dụ ngày lễ) để hook, lời thoại, caption và hashtag xoay quanh chủ đề đó. Bấm vào ô để xem gợi ý các ngày lễ trong năm.
      </p>
    </div>
  );
}
