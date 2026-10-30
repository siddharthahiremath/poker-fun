"use client";

import { Avatar, Card, Countdown, Num, percent } from "@/components/pieces";
import { chips, seatPoint, type SeatAction, type SeatState, type Turn, type Winner } from "@/lib/use-table";

const TONES: Record<SeatAction["tone"], string> = {
  aggressive: "bg-zinc-100 text-zinc-900",
  passive: "bg-zinc-100 text-zinc-900",
  fold: "bg-zinc-100 text-zinc-500",
  blind: "bg-zinc-100 text-zinc-600",
};

export function Seat({
  seat,
  index,
  total,
  turn,
  limit,
  action,
  winner,
  showdown,
  favorite,
  compact,
}: {
  seat: SeatState;
  index: number;
  total: number;
  turn: Turn | null;
  limit: number;
  action?: SeatAction;
  winner?: Winner;
  showdown: boolean;
  favorite: boolean;
  compact: boolean;
}) {
  const point = seatPoint(index, total);
  const thinking = turn?.seat === index;
  const busted = seat.status === "out" || (showdown && seat.stack === 0 && !winner);
  const folded = seat.status === "folded";
  const odds = !showdown && !folded ? seat.win_odds : null;
  const border = thinking ? "border-zinc-900" : "border-line";

  return (
    <div
      className={`absolute z-20 -translate-x-1/2 -translate-y-1/2 transition-opacity duration-300 ${busted ? "opacity-40" : ""}`}
      style={{ left: `${point.x}%`, top: `${point.y}%` }}
    >
      {seat.status !== "out" && (
        <div className="absolute bottom-[calc(100%-16px)] left-1/2 flex -translate-x-1/2 -space-x-2">
          {seat.cards.map((card, k) => (
            <div key={card} className={k === 0 ? "-rotate-6" : "translate-y-0.5 rotate-6"}>
              <Card card={card} dim={folded} highlight={!!winner?.hand_name && showdown} delay={k * 50} />
            </div>
          ))}
        </div>
      )}

      <div
        className={`relative flex items-center rounded-xl border bg-panel py-2 pl-2 shadow-[0_8px_20px_-12px_rgba(24,24,27,0.35)] transition-colors duration-150 ${compact ? "w-40 gap-2 pr-2" : "w-48 gap-3 pr-3"} ${border}`}
      >
        <Avatar
          name={seat.name}
          index={index}
          turnId={turn?.id}
          startedAt={thinking ? turn?.startedAt : undefined}
          limit={limit}
          thinking={thinking}
          small={compact}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-zinc-900">{seat.name}</div>
          <div className="flex items-baseline gap-2 whitespace-nowrap text-xs">
            <Num value={seat.stack} className="text-zinc-500" />
            {thinking && turn && <Countdown startedAt={turn.startedAt} limit={limit} />}
            {seat.status === "all-in" && !showdown && <span className="font-medium text-red-700">All-in</span>}
            {busted && <span className="font-medium text-zinc-500">Busted</span>}
            {folded && !busted && <span className="text-zinc-500">Folded</span>}
          </div>
          {seat.hand_name && !folded && (
            <div className={`truncate text-xs ${winner ? "font-medium text-zinc-900" : "text-zinc-600"}`}>{seat.hand_name}</div>
          )}
        </div>

        {odds !== null && (
          <div className="flex flex-col items-end leading-tight" title="Chance to win this hand">
            <span className={`tabular-nums ${compact ? "text-sm" : "text-base"} ${favorite ? "font-medium text-zinc-900" : "text-zinc-500"}`}>
              {percent(odds)}
            </span>
            {!compact && <span className="text-xs text-zinc-500">to win</span>}
          </div>
        )}

        {action && !showdown && (
          <div key={action.label + action.note} className="pop-in absolute -bottom-3 right-3 flex items-center gap-1">
            {action.note && (
              <span className="rounded bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">{action.note}</span>
            )}
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${TONES[action.tone]}`}>{action.label}</span>
          </div>
        )}

        {winner && showdown && (
          <div className="float-up absolute -top-5 left-1/2 whitespace-nowrap text-sm font-medium tabular-nums text-green-800">
            +{chips(winner.chips)}
          </div>
        )}
      </div>
    </div>
  );
}
