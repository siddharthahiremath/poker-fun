"use client";

import { Card, Num, seatColor } from "@/components/pieces";
import type { FeedItem, Snapshot, Turn } from "@/lib/use-table";

const FEED_TONES: Record<string, string> = {
  aggressive: "text-zinc-900",
  passive: "text-zinc-900",
  fold: "text-zinc-500",
  blind: "text-zinc-500",
  bad: "text-red-700",
  win: "text-green-800",
};

function Section({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-zinc-900">{title}</h2>
        {meta && <span className="text-xs text-zinc-500">{meta}</span>}
      </header>
      {children}
    </section>
  );
}

function Dot({ seat }: { seat: number }) {
  return <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: seatColor(seat) }} />;
}

export function Standings({ snap, turn }: { snap: Snapshot | null; turn: Turn | null }) {
  if (!snap) {
    return (
      <Section title="Chip count">
        <p className="text-sm text-zinc-500">Waiting for seats</p>
      </Section>
    );
  }
  const total = snap.seats.reduce((sum, seat) => sum + seat.stack, 0) + (snap.event === "showdown" ? 0 : snap.pot);
  const start = total / snap.seats.length;
  const top = Math.max(...snap.seats.map((seat) => seat.stack), 1);
  const ranked = snap.seats.map((seat, i) => ({ seat, i })).sort((a, b) => b.seat.stack - a.seat.stack);

  return (
    <Section title="Chip count" meta={`${snap.seats.length} agents, vs start`}>
      <ol className="flex flex-col">
        {ranked.map(({ seat, i }, rank) => {
          const delta = Math.round(seat.stack - start);
          const out = seat.stack === 0 && seat.status !== "all-in";
          return (
            <li key={i} className={`flex flex-col gap-1 py-2 ${out ? "opacity-40" : ""}`}>
              <div className="flex items-center gap-3 text-sm">
                <span className="w-4 text-xs text-zinc-500">{rank + 1}</span>
                <Dot seat={i} />
                <span className="flex-1 truncate text-zinc-900">{seat.name}</span>
                {turn?.seat === i && <span className="text-xs font-medium text-zinc-900">thinking</span>}
                <span className={`w-12 text-right text-xs ${delta > 0 ? "text-green-800" : delta < 0 ? "text-red-700" : "text-zinc-500"}`}>
                  {delta >= 0 ? "+" : ""}
                  {delta.toLocaleString("en-US")}
                </span>
                <Num value={seat.stack} className="w-14 text-right font-medium text-zinc-900" />
              </div>
              <div className="ml-12 h-1 overflow-hidden rounded-sm bg-line">
                <div
                  className={`h-full w-full origin-left transition-transform duration-300 ${seat.stack > 0 && seat.stack === top ? "bg-zinc-900" : "bg-zinc-300"}`}
                  style={{ transform: `scaleX(${Math.min(1, seat.stack / top)})` }}
                />
              </div>
            </li>
          );
        })}
      </ol>
    </Section>
  );
}

export function Feed({ feed, snap }: { feed: FeedItem[]; snap: Snapshot | null }) {
  return (
    <Section title="Action">
      <ol className="feed-scroll -mr-2 flex max-h-[416px] flex-col overflow-y-auto pr-2">
        {feed.length === 0 && <li className="py-2 text-sm text-zinc-500">Nothing yet. The first hand is being dealt.</li>}
        {feed.map((item) => {
          if (item.kind === "hand") {
            return (
              <li key={item.id} className="mt-4 flex h-8 items-center justify-between first:mt-0">
                <span className="text-xs font-medium text-zinc-900">{item.text}</span>
                <span className="text-xs text-zinc-500">{item.meta}</span>
              </li>
            );
          }
          if (item.kind === "street") {
            return (
              <li key={item.id} className="flex min-h-10 items-center gap-3">
                <span className="w-16 text-xs font-medium text-zinc-500">{item.text}</span>
                <span className="flex gap-1">
                  {item.cards?.map((card) => <Card key={card} card={card} size="xs" />)}
                </span>
              </li>
            );
          }
          const name = item.seat !== undefined ? snap?.seats[item.seat]?.name : "";
          return (
            <li key={item.id} className="flex min-h-10 items-center gap-3">
              <Dot seat={item.seat ?? 0} />
              <span className="min-w-0 flex-1 text-sm text-zinc-600">
                <span className="font-medium text-zinc-900">{name}</span>{" "}
                <span className={FEED_TONES[item.tone ?? "passive"]}>{item.text}</span>
              </span>
              {item.cards && (
                <span className="flex gap-0.5">
                  {item.cards.map((card) => <Card key={card} card={card} size="xs" />)}
                </span>
              )}
              {item.meta && <span className="text-xs text-zinc-500">{item.meta}</span>}
            </li>
          );
        })}
      </ol>
    </Section>
  );
}
