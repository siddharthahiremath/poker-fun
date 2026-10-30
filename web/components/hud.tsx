"use client";

import { Card, Countdown, seatColor } from "@/components/pieces";
import { chips, type Snapshot, type Story, type Turn } from "@/lib/use-table";

const STEPS = ["preflop", "flop", "turn", "river", "showdown"];

const TONES: Record<string, string> = {
  aggressive: "text-zinc-900",
  passive: "text-zinc-900",
  fold: "text-zinc-500",
  blind: "text-zinc-600",
  bad: "text-red-700",
  win: "text-green-800",
};

function Name({ seat, snap }: { seat: number; snap: Snapshot }) {
  return (
    <span className="inline-flex items-center gap-2 text-zinc-900">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: seatColor(seat) }} />
      {snap.seats[seat]?.name}
    </span>
  );
}

export function Hud({ snap, turn, story }: { snap: Snapshot | null; turn: Turn | null; story: Story | null }) {
  if (!snap) {
    return <p className="h-20 text-base text-zinc-500">Shuffling up. The first hand is on its way.</p>;
  }
  const step = snap.event === "showdown" || snap.event === "final" ? 4 : STEPS.indexOf(snap.street);
  const actor = turn ? snap.seats[turn.seat] : null;
  const owed = actor ? Math.min(actor.stack, Math.max(0, snap.current_bet - actor.bet)) : 0;
  const doubling = snap.blinds_double_in === 1 ? "double next hand" : `double in ${snap.blinds_double_in} hands`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-zinc-500">
        <span className="font-medium text-zinc-900">Hand {snap.hand}</span>
        <ol className="flex items-center gap-3" aria-label="Street">
          {STEPS.map((name, k) => (
            <li
              key={name}
              aria-current={k === step ? "step" : undefined}
              className={`capitalize ${
                k === step
                  ? "border-b border-zinc-900 font-medium text-zinc-900"
                  : k < step
                    ? "text-zinc-600"
                    : "text-zinc-500"
              }`}
            >
              {name}
            </li>
          ))}
        </ol>
        <span>
          Blinds <span className="text-zinc-900">{chips(snap.blinds[0])}/{chips(snap.blinds[1])}</span>
          {snap.blinds_double_in > 0 && (
            <span className={snap.blinds_double_in === 1 ? "font-medium text-zinc-900" : ""}>, {doubling}</span>
          )}
        </span>
        <span>{snap.time_limit}s per move</span>
      </div>

      <div className="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-1 text-2xl font-medium" aria-live="polite">
        {turn && actor ? (
          <>
            <Name seat={turn.seat} snap={snap} />
            <span className="text-zinc-500">is thinking</span>
            <Countdown startedAt={turn.startedAt} limit={snap.time_limit} />
            <span className="text-sm font-normal tracking-normal text-zinc-500">
              {owed ? `${chips(owed)} to call` : "can check"} into a pot of {chips(snap.pot)}
            </span>
          </>
        ) : story ? (
          <span key={story.id} className="pop-in inline-flex flex-wrap items-center gap-x-3 gap-y-1">
            {story.seat !== undefined && <Name seat={story.seat} snap={snap} />}
            <span className={TONES[story.tone ?? "passive"]}>{story.text}</span>
            {story.cards && (
              <span className="flex gap-1">
                {story.cards.map((card) => <Card key={card} card={card} size="sm" />)}
              </span>
            )}
          </span>
        ) : null}
      </div>
    </div>
  );
}
