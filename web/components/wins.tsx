"use client";

import { Num, seatColor } from "@/components/pieces";
import type { Snapshot } from "@/lib/use-table";

export function WinsChart({ snap }: { snap: Snapshot | null }) {
  if (!snap) {
    return <p className="text-sm text-zinc-500">Waiting for seats</p>;
  }

  const wins = snap.seats.map((_, i) => snap.wins?.[i] ?? 0);
  const top = Math.max(...wins, 0);
  const ranked = snap.seats
    .map((seat, i) => ({ seat, i, wins: wins[i] }))
    .sort((a, b) => b.wins - a.wins || a.i - b.i);

  return (
    <section className="flex flex-col gap-6">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-900">Wins</h2>
        <span className="text-xs text-zinc-500">
          {top === 0 ? "No hands yet" : top === 1 ? "1 hand taken" : `${top} hands taken`}
        </span>
      </header>
      <ol className="flex h-80 items-end gap-4">
        {ranked.map(({ seat, i, wins: count }) => {
          const leading = count > 0 && count === top;
          return (
            <li key={i} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-3">
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
                <span className="truncate">{seat.name}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
