export const TIME_MIN = 1;
export const TIME_MAX = 30;
export const TIME_DEFAULT = 10;

export type Mode = "table" | "wins";

export function readTime(raw: string | null) {
  const value = Number(raw);
  if (!Number.isFinite(value)) return TIME_DEFAULT;
  return Math.min(TIME_MAX, Math.max(TIME_MIN, Math.round(value)));
}
