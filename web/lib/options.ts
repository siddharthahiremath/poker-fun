export const TIME_MIN = 0.001;
export const TIME_MAX = 30;
export const TIME_DEFAULT = 10;

export type Mode = "table" | "wins";
export type TimeWhen = "now" | "hand";

export function readTime(raw: string | null) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return TIME_DEFAULT;
  const clamped = Math.min(TIME_MAX, Math.max(TIME_MIN, value));
  return Math.round(clamped * 1000) / 1000;
}

export function formatSeconds(value: number) {
  const rounded = Math.round(value * 1000) / 1000;
  return String(rounded);
}
