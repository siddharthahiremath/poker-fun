"use client";

import { useEffect, useRef, useState } from "react";
import { Num, seatColor } from "@/components/pieces";
import { compare, describe, type Call } from "@/lib/confidence";
import type { Snapshot } from "@/lib/use-table";

const SIDE_COLOR = {
  better: "text-green-800",
  worse: "text-red-700",
  even: "text-zinc-500",
} as const;

function align(place: number, count: number) {
  if (place === 0) return "left-0";
  if (place === count - 1) return "right-0";
  return "left-1/2 -translate-x-1/2";
}

function Confidence({
  player,
  calls,
  place,
  count,
}: {
  player: string;
  calls: Call[];
  place: number;
  count: number;
}) {
  const separated = calls.some((call) => call.side !== "even");
  return (
    <div
      role="tooltip"
      aria-hidden="true"
      className={`absolute bottom-12 z-20 w-72 rounded-xl border border-line bg-panel p-3 text-left shadow-[0_12px_32px_-18px_rgba(24,24,27,0.4)] ${align(place, count)}`}
    >
      <p className="text-xs text-zinc-500">How sure {player} is better or worse</p>
      {calls.length === 0 ? (
        <p className="mt-2 text-sm text-zinc-600">No finished games yet.</p>
      ) : separated ? (
        <ul className="feed-scroll mt-2 flex max-h-48 flex-col gap-1.5 overflow-y-auto">
          {calls.map((call) => (
            <li key={call.index} className="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-x-2 text-sm leading-5">
              <span className="font-medium tabular-nums text-zinc-900">{call.label}</span>
              <span className="text-zinc-600">
                {call.side === "even" ? (
                  <>
                    even with <span className="text-zinc-900">{call.name}</span>
                  </>
                ) : (
                  <>
                    sure <span className={SIDE_COLOR[call.side]}>{call.side}</span> than{" "}
                    <span className="text-zinc-900">{call.name}</span>
                  </>
                )}
                {call.significant && <span className="text-zinc-500">, significant</span>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-zinc-600">Too close to call. The wins don&apos;t separate them yet.</p>
      )}
      {calls.length > 0 && <p className="mt-2 text-xs text-zinc-500">95% and up is a significant gap.</p>}
    </div>
  );
}

export function WinsChart({ snap }: { snap: Snapshot | null }) {
  const [open, setOpen] = useState<number | null>(null);
  const chart = useRef<HTMLOListElement>(null);
  const lineupKey = snap?.seats.map((seat) => seat.name).join("\0") ?? "";
  const [lineupSeen, setLineupSeen] = useState(lineupKey);
  if (lineupKey !== lineupSeen) {
    setLineupSeen(lineupKey);
    setOpen(null);
  }

  useEffect(() => {
    if (open === null) return;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && chart.current?.contains(event.target)) return;
      setOpen(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!snap) {
    return <p className="text-sm text-zinc-500">Waiting for seats</p>;
  }

  const wins = snap.seats.map((_, i) => snap.wins?.[i] ?? 0);
  const top = Math.max(...wins, 0);
  const played = snap.game ?? wins.reduce((sum, count) => sum + count, 0);
  const finished = wins.reduce((sum, count) => sum + count, 0);
  const ranked = snap.seats
    .map((seat, i) => ({ seat, i, wins: wins[i] }))
    .sort((a, b) => b.wins - a.wins || a.i - b.i);

  return (
    <section className="flex flex-col gap-6">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-900">Wins</h2>
        <span className="text-xs text-zinc-500">
          {played === 0 ? "No games yet" : played === 1 ? "1 game" : `${played} games`}
        </span>
      </header>
      <ol ref={chart} className="flex h-80 items-end gap-4">
        {ranked.map(({ seat, i, wins: count }, place) => {
          const leading = count > 0 && count === top;
          const shown = open === i;
          const calls =
            finished > 0
              ? ranked.filter((player) => player.i !== i).map((player) => compare(count, player.wins, player.seat.name, player.i))
              : [];
          const separated = calls.some((call) => call.side !== "even");
          const summary =
            finished === 0
              ? `${seat.name}, no finished games yet`
              : !separated
                ? `${seat.name}. Too close to call. The wins don't separate them yet. 95% and up is a significant gap.`
                : `${seat.name}. ${calls.map((call) => describe(seat.name, call)).join(". ")}. 95% and up is a significant gap.`;
          return (
            <li
              key={i}
              tabIndex={0}
              aria-label={summary}
              onMouseEnter={() => setOpen(i)}
              onMouseLeave={(event) => {
                if (event.currentTarget === document.activeElement) return;
                setOpen((current) => (current === i ? null : current));
              }}
              onFocus={() => setOpen(i)}
              onBlur={(event) => {
                const next = event.relatedTarget;
                if (next instanceof Node && event.currentTarget.contains(next)) return;
                setOpen((current) => (current === i ? null : current));
              }}
              onPointerDown={(event) => {
                if (event.pointerType === "touch") setOpen(i);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setOpen(null);
                  event.currentTarget.blur();
                }
              }}
              className={`relative flex h-full min-w-0 flex-1 cursor-help flex-col justify-end gap-3 rounded-md outline-none ${shown ? "z-20" : ""}`}
            >
              {shown && <Confidence player={seat.name} calls={calls} place={place} count={ranked.length} />}
              <Num value={count} className="text-center text-sm font-medium text-zinc-900" />
              <div className="relative h-64 w-full overflow-hidden rounded-md bg-zinc-100">
                <div
                  className={`absolute inset-x-0 bottom-0 h-full origin-bottom transition-transform duration-300 ${
                    leading ? "bg-zinc-900" : "bg-zinc-300"
                  }`}
                  style={{ transform: `scaleY(${top === 0 ? 0 : count / top})` }}
                />
              </div>
              <div className="flex items-center justify-center gap-2 text-sm text-zinc-900">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: seatColor(i) }} />
                <span className={`truncate ${shown ? "underline decoration-zinc-300 underline-offset-4" : ""}`}>{seat.name}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
