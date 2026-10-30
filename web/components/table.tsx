"use client";

import { useEffect, useRef, useState } from "react";
import { Card, ChipStack, EmptyCard, Num } from "@/components/pieces";
import { Seat } from "@/components/seat";
import { chips, seatPoint, type Flight, type SeatAction, type Snapshot, type Spot, type Turn } from "@/lib/use-table";

// Seats are fixed-size, so the table is drawn at one size and scaled to fit; narrow screens get a tall layout.
// `area` is the inset (px) of the rectangle seats sit on, leaving room for their plates and cards inside the box.
const WIDE = {
  width: 1060,
  height: 600,
  area: { x: 120, top: 92, bottom: 48 },
  board: { size: "lg" as const, top: 54 },
  pot: { x: 50, y: 33 },
  bets: 0.58,
  showBets: true,
};
const TALL = {
  width: 480,
  height: 680,
  area: { x: 88, top: 88, bottom: 44 },
  board: { size: "md" as const, top: 47 },
  pot: { x: 50, y: 62 },
  // no room for bet stacks here; the seat's action pill already shows the amount
  bets: 0.8,
  showBets: false,
};

function useFit() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(WIDE.width);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const canvas = width < 640 ? TALL : WIDE;
  return { ref, canvas, scale: Math.min(1, width / canvas.width) };
}

export function Table({
  snap,
  turn,
  actions,
  flights,
  finished,
  onRestart,
}: {
  snap: Snapshot | null;
  turn: Turn | null;
  actions: Record<number, SeatAction>;
  flights: Flight[];
  finished: boolean;
  onRestart: () => void;
}) {
  const { ref, canvas, scale } = useFit();
  const n = snap?.seats.length ?? 0;
  const showdown = snap?.event === "showdown";
  const winners = new Map((showdown ? (snap?.winners ?? []) : []).map((w) => [w.seat, w]));
  const headline = showdown ? snap?.winners?.[0] : undefined;
  const champion = snap && finished ? snap.seats.reduce((best, seat) => (seat.stack > best.stack ? seat : best)) : null;
  const button = snap ? seatPoint(snap.button, n, 0.74, 0.32) : null;
  const odds = snap?.seats.map((seat) => (seat.status === "folded" ? 0 : (seat.win_odds ?? 0))) ?? [];
  const favorite = odds.length ? odds.indexOf(Math.max(...odds)) : -1;
  const betPoint = (i: number) => seatPoint(i, n, canvas.bets);
  const place = (spot: Spot) => (spot === "pot" ? canvas.pot : spot.at === "bet" ? betPoint(spot.seat) : seatPoint(spot.seat, n));
  const at = (point: { x: number; y: number }) => ({ left: `${point.x}%`, top: `${point.y}%` });

  return (
    <div ref={ref} className="relative w-full" style={{ height: canvas.height * scale }}>
      <div
        className="absolute left-1/2 top-0 origin-top rounded-xl border border-line bg-surface shadow-[0_12px_32px_-20px_rgba(24,24,27,0.25)]"
        style={{ width: canvas.width, height: canvas.height, transform: `translateX(-50%) scale(${scale})` }}
      >
        {!snap && <div className="absolute inset-0 grid place-items-center text-sm text-zinc-500">Dealing the first hand</div>}

        {snap && champion && (
          <div className="absolute inset-0 z-30 grid place-items-center">
            <div className="pop-in flex flex-col items-center gap-4 text-center">
              <h2 className={`font-medium text-zinc-900 ${canvas === TALL ? "text-2xl" : "text-4xl"}`}>
                {champion.name} takes the table
              </h2>
              <p className="text-sm text-zinc-500">
                Finished with <Num value={champion.stack} /> chips after {snap.hand} hands.
              </p>
              <button
                onClick={onRestart}
                className="mt-2 inline-flex h-9 items-center rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white transition-[background-color,transform] duration-150 hover:bg-zinc-700 active:scale-[0.98]"
              >
                Run it back
              </button>
            </div>
          </div>
        )}

        <div
          className="absolute"
          style={{ left: canvas.area.x, right: canvas.area.x, top: canvas.area.top, bottom: canvas.area.bottom }}
        >
          {snap && !champion && (
            <>
              <div className="absolute z-10 -translate-x-1/2 -translate-y-1/2" style={at(canvas.pot)}>
                {headline ? (
                  <div
                    key={`${snap.hand}-win`}
                    className="pop-in whitespace-nowrap rounded-lg border border-line bg-panel px-4 py-2 text-sm text-zinc-900"
                  >
                    {snap.seats[headline.seat].name} wins <span className="font-medium tabular-nums">{chips(headline.chips)}</span>
                    {headline.hand_name ? ` with ${headline.hand_name.toLowerCase()}` : ", everyone folded"}
                    {(snap.winners?.length ?? 0) > 1 ? ` (split ${snap.winners?.length} ways)` : ""}
                  </div>
                ) : (
                  <div className="flex items-center gap-3 rounded-lg border border-line bg-panel py-1 pl-2 pr-4">
                    <ChipStack amount={snap.pot} max={5} />
                    <span className="text-sm text-zinc-500">Pot</span>
                    <Num value={snap.pot} className="text-base font-medium text-zinc-900" />
                  </div>
                )}
              </div>

              <div
                className="absolute left-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 gap-2 [perspective:800px]"
                style={{ top: `${canvas.board.top}%` }}
              >
                {Array.from({ length: 5 }, (_, k) =>
                    snap.board[k] ? (
                    <Card key={snap.board[k]} card={snap.board[k]} size={canvas.board.size} delay={k < 3 ? k * 50 : 0} />
                  ) : (
                    <EmptyCard key={k} size={canvas.board.size} />
                  ),
                )}
              </div>

              {!showdown &&
                canvas.showBets &&
                snap.seats.map((seat, i) =>
                  seat.bet > 0 ? (
                    <div
                      key={`bet-${i}`}
                      className="absolute z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2"
                      style={at(betPoint(i))}
                    >
                      <ChipStack amount={seat.bet} />
                      <span className="text-xs tabular-nums text-zinc-600">{chips(seat.bet)}</span>
                    </div>
                  ) : null,
                )}

              {button && (
                <div
                  className="absolute z-10 grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-zinc-900 text-xs font-medium text-white"
                  role="img"
                  aria-label="Dealer"
                  style={at(button)}
                  title="Dealer"
                >
                  D
                </div>
              )}

              {snap.seats.map((seat, i) => (
                <Seat
                  key={i}
                  seat={seat}
                  index={i}
                  total={n}
                  turn={turn}
                  limit={snap.time_limit}
                  action={actions[i]}
                  winner={winners.get(i)}
                  showdown={showdown}
                  favorite={i === favorite && odds[i] > 0}
                  compact={canvas === TALL}
                />
              ))}
            </>
          )}

          {n > 0 &&
            flights.map((flight) => {
              const from = place(flight.from);
              const to = place(flight.to);
              return (
                <div
                  key={flight.id}
                  className="fly-x pointer-events-none z-30"
                  style={{ ["--x0" as string]: `${from.x}%`, ["--x1" as string]: `${to.x}%`, animationDelay: `${flight.delay}ms` }}
                >
                  <div
                    className="fly-y"
                    style={{ ["--y0" as string]: `${from.y}%`, ["--y1" as string]: `${to.y}%`, animationDelay: `${flight.delay}ms` }}
                  >
                    <div className="chip fly-spin" style={{ ["--chip" as string]: flight.color, animationDelay: `${flight.delay}ms` }} />
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
