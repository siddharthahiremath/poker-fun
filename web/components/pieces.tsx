"use client";

import { useEffect, useRef, useState } from "react";

const PALETTE = ["#9c3d3d", "#2f6484", "#6a5438", "#2f684c", "#8a5a28", "#4a596e", "#7d3f58", "#556332", "#8a4e32", "#3d5270"];

export const seatColor = (i: number) => PALETTE[i % PALETTE.length];

export function useTween(value: number, ms = 600) {
  const [shown, setShown] = useState(value);
  const current = useRef(value);
  useEffect(() => {
    const from = current.current;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - progress, 3);
      current.current = Math.round(from + (value - from) * eased);
      setShown(current.current);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, ms]);
  return shown;
}

export function Num({ value, className = "" }: { value: number; className?: string }) {
  return <span className={`tabular-nums ${className}`}>{useTween(value).toLocaleString("en-US")}</span>;
}

const CARD_SIZES = {
  xs: { box: "h-9 w-6", rank: "left-1 top-0.5 text-xs", suit: "bottom-0 right-0.5 text-xs" },
  sm: { box: "h-14 w-10", rank: "left-1 top-1 text-sm", suit: "bottom-1 right-1 text-base" },
  md: { box: "h-16 w-12", rank: "left-2 top-1 text-base", suit: "bottom-1 right-2 text-2xl" },
  lg: { box: "h-20 w-14", rank: "left-2 top-2 text-base", suit: "bottom-2 right-2 text-2xl" },
};

export function Card({
  card,
  size = "sm",
  dim = false,
  highlight = false,
  delay = 0,
}: {
  card: string;
  size?: keyof typeof CARD_SIZES;
  dim?: boolean;
  highlight?: boolean;
  delay?: number;
}) {
  const suit = card.slice(-1);
  const color = suit === "♥" || suit === "♦" ? "text-rose-600" : "text-zinc-900";
  const style = CARD_SIZES[size];
  return (
    <div
      className={`card-face relative shrink-0 select-none rounded-md transition-[opacity,outline-color] duration-300 ${style.box} ${
        dim ? "opacity-40" : ""
      } ${highlight ? "outline-2 outline-offset-2 outline-zinc-900" : "outline-transparent"}`}
      style={{ animationDelay: `${delay}ms` }}
    >
      <span className={`absolute font-medium leading-none ${color} ${style.rank}`}>{card.slice(0, -1)}</span>
      <span className={`absolute leading-none ${color} ${style.suit}`}>{suit}</span>
    </div>
  );
}

export function EmptyCard({ size = "lg" }: { size?: "md" | "lg" }) {
  return <div className={`shrink-0 rounded-md border border-dashed border-zinc-300 ${CARD_SIZES[size].box}`} />;
}

const DENOMINATIONS: [number, string][] = [
  [1000, "#d9a43a"],
  [500, "#7c5cd6"],
  [100, "#1f2430"],
  [25, "#13a374"],
  [5, "#e0475f"],
  [1, "#aeb6c2"],
];

export function ChipStack({ amount, max = 7 }: { amount: number; max?: number }) {
  const stack: string[] = [];
  let rest = amount;
  for (const [value, color] of DENOMINATIONS) {
    while (rest >= value && stack.length < max) {
      stack.push(color);
      rest -= value;
    }
  }
  return (
    <div className="relative h-5 w-5" style={{ marginTop: (stack.length - 1) * 3 }}>
      {stack.map((color, k) => (
        <div key={k} className="chip absolute left-0" style={{ top: -k * 3, ["--chip" as string]: color }} />
      ))}
    </div>
  );
}

export function Avatar({
  name,
  index,
  turnId,
  startedAt,
  limit,
  thinking,
  small = false,
}: {
  name: string;
  index: number;
  turnId?: number;
  startedAt?: number;
  limit: number;
  thinking: boolean;
  small?: boolean;
}) {
  const circumference = 2 * Math.PI * 22;
  return (
    <div className={`relative grid shrink-0 place-items-center ${small ? "h-9 w-9" : "h-12 w-12"}`}>
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 48 48" aria-hidden>
        <circle cx="24" cy="24" r="22" fill="none" stroke="var(--color-line)" strokeWidth="3" />
        {thinking && (
          <circle
            key={`${turnId}-${limit}`}
            className="timer-ring"
            cx="24"
            cy="24"
            r="22"
            fill="none"
            strokeWidth="3"
            strokeLinecap="round"
            style={{
              ["--c" as string]: `${circumference}`,
              ["--limit" as string]: `${Math.max(limit, 0.001)}s`,
              animationDelay: `${startedAt ? -Math.max(0, (Date.now() - startedAt) / 1000) : 0}s`,
            }}
          />
        )}
      </svg>
      <div
        className={`grid place-items-center rounded-full bg-zinc-100 font-medium text-zinc-900 ${small ? "h-6 w-6 text-xs" : "h-9 w-9 text-sm"}`}
      >
        {name.slice(0, 1).toUpperCase()}
      </div>
      <span
        aria-hidden
        className="absolute right-1 bottom-1 z-10 h-2 w-2 rounded-full ring-2 ring-white"
        style={{ background: seatColor(index) }}
      />
    </div>
  );
}

export function Countdown({ startedAt, limit }: { startedAt: number; limit: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 50);
    return () => window.clearInterval(timer);
  }, []);
  const left = Math.max(0, limit - (now - startedAt) / 1000);
  const color = left > limit * 0.45 ? "text-zinc-500" : left > limit * 0.15 ? "text-zinc-900" : "text-red-700";
  const digits = limit < 0.1 ? 3 : limit < 10 ? 2 : 1;
  return <span className={`font-medium tabular-nums ${color}`}>{left.toFixed(digits)}s</span>;
}

export const percent = (odds: number) => (odds > 0 && odds < 0.01 ? "<1%" : `${Math.round(odds * 100)}%`);
