"use client";

import { Num, seatColor } from "@/components/pieces";
import { compare } from "@/lib/confidence";
import type { Snapshot } from "@/lib/use-table";

function Name({ seat, name }: { seat: number; name: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-zinc-900">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: seatColor(seat) }} />
      {name}
    </span>
  );
}

export function WinsChart({ snap }: { snap: Snapshot | null }) {
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
  const pairs = ranked.flatMap((hi, index) =>
    ranked.slice(index + 1).map((lo) => ({
      hi,
      lo,
      call: compare(hi.wins, lo.wins, lo.seat.name, lo.i),
    })),
  );
  const separated = pairs.some((pair) => pair.call.side !== "even");

  return (
    <section className="flex flex-col gap-6">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-900">Wins</h2>
        <span className="text-xs text-zinc-500">
          {played === 0 ? "No games yet" : played === 1 ? "1 game" : `${played} games`}
        </span>
      </header>
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-zinc-500">How sure</h3>
        {finished === 0 ? (
          <p className="text-sm text-zinc-600">No finished games yet.</p>
        ) : !separated ? (
          <p className="text-sm text-zinc-600">Too close to call. The wins don&apos;t separate them yet.</p>
        ) : (
          <ul className="flex flex-col">
            {pairs.map(({ hi, lo, call }) => (
              <li key={`${hi.i}-${lo.i}`} className="flex items-baseline gap-3 py-1 text-sm">
                <span className="w-12 shrink-0 font-medium tabular-nums text-zinc-900">{call.label}</span>
                <span className="min-w-0 text-zinc-600">
                  {call.side === "even" ? (
                    <>
                      <Name seat={hi.i} name={hi.seat.name} /> and <Name seat={lo.i} name={lo.seat.name} /> are even
                    </>
                  ) : (
                    <>
                      sure <Name seat={hi.i} name={hi.seat.name} /> is <span className="text-green-800">better</span> than{" "}
                      <Name seat={lo.i} name={lo.seat.name} />
                    </>
                  )}
                </span>
                {call.significant && <span className="ml-auto shrink-0 text-xs text-zinc-500">significant</span>}
              </li>
            ))}
          </ul>
        )}
        {finished > 0 && <p className="text-xs text-zinc-500">95% and up is a significant gap.</p>}
      </div>
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
