"use client";

import { useEffect, useRef, useState } from "react";
import type { Mode } from "@/lib/options";

export type Status = "active" | "folded" | "all-in" | "out";
export type Tone = "aggressive" | "passive" | "fold" | "blind";
export type Connection = "connecting" | "live" | "finished" | "error";
export type Lineup = "demo" | "real";

export type SeatState = {
  name: string;
  stack: number;
  bet: number;
  cards: string[];
  status: Status;
  hand_name: string | null;
  win_odds: number | null;
};

export type Winner = { seat: number; chips: number; hand_name: string | null };

export type Snapshot = {
  event: "hand" | "thinking" | "action" | "street" | "showdown" | "final" | "game" | "clock";
  hand: number;
  street: string;
  board: string[];
  pot: number;
  button: number;
  blinds: [number, number];
  blinds_double_in: number;
  current_bet: number;
  time_limit: number;
  time_pending?: number | null;
  game?: number | null;
  wins?: number[];
  winner?: number;
  seats: SeatState[];
  actor?: number;
  action?: { seat: number; street: string; action: string; to: number; note: string };
  winners?: Winner[];
  shown?: number[];
};

export type Point = { x: number; y: number };
export type Turn = { seat: number; startedAt: number; id: number };
export type SeatAction = { label: string; tone: Tone; note: string };
// where chips fly between; the table turns these into coordinates for its current layout
export type Spot = { seat: number; at: "seat" | "bet" } | "pot";
export type Flight = { id: number; from: Spot; to: Spot; delay: number; color: string };
export type FeedItem = {
  id: number;
  kind: "hand" | "street" | "action" | "win" | "final";
  text: string;
  seat?: number;
  meta?: string;
  tone?: Tone | "bad" | "win";
  cards?: string[];
};
// the latest thing that happened, in one line
export type Story = Omit<FeedItem, "kind" | "meta">;

// seats sit around the edge of the table area, clockwise from bottom center
export function seatPoint(i: number, n: number, scale = 1, shift = 0): Point {
  const angle = Math.PI / 2 + (i / n) * Math.PI * 2 + shift;
  const [cos, sin] = [Math.cos(angle), Math.sin(angle)];
  const edge = 1 / Math.max(Math.abs(cos), Math.abs(sin)); // push the point out onto the rectangle
  return { x: 50 + cos * edge * 50 * scale, y: 50 + sin * edge * 50 * scale };
}

const seat = (i: number): Spot => ({ seat: i, at: "seat" });
const bet = (i: number): Spot => ({ seat: i, at: "bet" });

export const chips = (value: number) => value.toLocaleString("en-US");

function describe(action: NonNullable<Snapshot["action"]>, after: SeatState, before?: SeatState) {
  const paid = after.bet - (before?.bet ?? 0);
  const allIn = after.status === "all-in";
  switch (action.action) {
    case "fold":
      return { label: "Fold", tone: "fold" as Tone, text: "folds" };
    case "check":
      return { label: "Check", tone: "passive" as Tone, text: "checks" };
    case "call":
      return allIn
        ? { label: `All-in ${chips(after.bet)}`, tone: "aggressive" as Tone, text: `calls all-in for ${chips(paid)}` }
        : { label: `Call ${chips(paid)}`, tone: "passive" as Tone, text: `calls ${chips(paid)}` };
    default: {
      const verb = action.action === "bet" ? "bets" : "raises to";
      return allIn
        ? { label: `All-in ${chips(action.to)}`, tone: "aggressive" as Tone, text: `shoves all-in to ${chips(action.to)}` }
        : {
            label: `${action.action === "bet" ? "Bet" : "Raise"} ${chips(action.to)}`,
            tone: "aggressive" as Tone,
            text: `${verb} ${chips(action.to)}`,
          };
    }
  }
}

const NOTES: Record<string, string> = {
  timeout: "timed out",
  crash: "crashed",
  illegal: "illegal move",
  "sitting out": "sitting out",
};

export function useTable(run: number, lineup: Lineup, timeLimit: number, mode: Mode) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [turn, setTurn] = useState<Turn | null>(null);
  const [actions, setActions] = useState<Record<number, SeatAction>>({});
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [story, setStory] = useState<Story | null>(null);
  const [flights, setFlights] = useState<Flight[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [error, setError] = useState<string | null>(null);
  const timeRef = useRef(timeLimit);
  timeRef.current = timeLimit;

  useEffect(() => {
    let live = true;
    const clear = () => {
      setSnap(null);
      setTurn(null);
      setActions({});
      setFeed([]);
      setStory(null);
      setFlights([]);
    };
    clear();
    setConnection("connecting");
    setError(null);

    // run 0 joins whatever game the server is showing; later runs ask for a fresh one
    // time is read here, not watched: changing it goes through POST so the hand keeps going
    const source = new EventSource(`/api/game?lineup=${lineup}&time=${timeRef.current}&mode=${mode}&restart=${run > 0 ? 1 : 0}`);
    const timers: number[] = [];
    let previous: Snapshot | null = null;
    let turnStartedAt = 0;
    let nextId = 0;

    source.addEventListener("reset", () => {
      if (!live) return;
      previous = null;
      clear();
    });

    const log = (item: Omit<FeedItem, "id">) => setFeed((items) => [{ ...item, id: nextId++ }, ...items].slice(0, 80));
    const tell = (item: Omit<Story, "id">) => setStory({ ...item, id: nextId++ });
    let fast = false;
    const fly = (from: Spot, to: Spot, delay = 0, color = "#f5b83d") => {
      if (fast) return;
      const batch = [0, 70, 140].map((stagger) => ({ id: nextId++, from, to, delay: delay + stagger, color }));
      const ids = new Set(batch.map((flight) => flight.id));
      setFlights((current) => [...current, ...batch]);
      timers.push(window.setTimeout(() => setFlights((current) => current.filter((f) => !ids.has(f.id))), delay + 1200));
    };

    const sweepBets = (from: Snapshot | null) =>
      from?.seats.forEach((state, i) => state.bet > 0 && fly(bet(i), "pot", 0, "#a1a1aa"));

    source.onmessage = (message) => {
      if (!live) return;
      let s: Snapshot;
      try {
        s = JSON.parse(message.data);
      } catch {
        return;
      }
      setConnection("live");
      fast = s.time_limit < 1;

      if (s.event === "clock") {
        setSnap((current) =>
          current ? { ...current, time_limit: s.time_limit, time_pending: s.time_pending ?? null } : current,
        );
        return;
      }

      if (s.event === "hand") {
        const blinds: Record<number, SeatAction> = {};
        s.seats.forEach((state, i) => {
          if (state.bet > 0) {
            blinds[i] = { label: `Blind ${chips(state.bet)}`, tone: "blind", note: "" };
            fly(seat(i), bet(i));
          }
        });
        setActions(blinds);
        setTurn(null);
        const blindsText = `${chips(s.blinds[0])}/${chips(s.blinds[1])}`;
        const doubled = previous && s.blinds[1] > previous.blinds[1];
        log({ kind: "hand", text: `Hand ${s.hand}`, meta: `Blinds ${blindsText}` });
        tell({
          text: doubled ? `Blinds doubled to ${blindsText}. Hand ${s.hand} is dealt.` : `Hand ${s.hand} is dealt. Blinds ${blindsText}.`,
          tone: doubled ? "bad" : "blind",
        });
      } else if (s.event === "street") {
        sweepBets(previous);
        setActions({});
        const street = s.street[0].toUpperCase() + s.street.slice(1);
        log({ kind: "street", text: street, cards: s.board });
        const dealt = s.street === "flop" ? s.board : s.board.slice(-1);
        tell({ text: `${street} comes`, tone: "passive", cards: dealt });      } else if (s.event === "thinking" && s.actor !== undefined) {
        turnStartedAt = Date.now();
        setTurn({ seat: s.actor, startedAt: turnStartedAt, id: nextId++ });      } else if (s.event === "action" && s.action) {
        const i = s.action.seat;
        const before = previous?.seats[i];
        const { label, tone, text } = describe(s.action, s.seats[i], before);
        const note = s.action.note;
        setActions((current) => ({ ...current, [i]: { label, tone, note } }));
        setTurn(null);
        if (s.seats[i].bet > (before?.bet ?? 0)) fly(seat(i), bet(i));
        const took = turnStartedAt ? `${((Date.now() - turnStartedAt) / 1000).toFixed(1)}s` : undefined;
        const said = note ? `${NOTES[note] ?? note}, so ${text}` : text;
        log({ kind: "action", seat: i, text: said, meta: took, tone: note ? "bad" : tone });
        tell({ seat: i, text: said, tone: note ? "bad" : tone });      } else if (s.event === "showdown") {
        setTurn(null);
        sweepBets(previous);
        const winners = s.winners ?? [];
        winners.forEach((winner) => {
          fly("pot", seat(winner.seat), 650);
          log({
            kind: "win",
            seat: winner.seat,
            text: `wins ${chips(winner.chips)}${winner.hand_name ? ` with ${winner.hand_name.toLowerCase()}` : ""}`,
            tone: "win",
            cards: winner.hand_name ? s.seats[winner.seat].cards : undefined,
          });
        });
        const top = winners[0];
        if (top) {
          const how = top.hand_name ? `with ${top.hand_name.toLowerCase()}` : "when everyone else folds";
          const split = winners.length > 1 ? `, splitting it ${winners.length} ways` : "";
          tell({ seat: top.seat, text: `wins ${chips(s.pot)} ${how}${split}`, tone: "win" });        }
      } else if (s.event === "game" && s.winner !== undefined) {
        setTurn(null);
        setActions({});
        log({ kind: "final", seat: s.winner, text: "wins the game", tone: "win" });
        tell({ seat: s.winner, text: "wins the game", tone: "win" });
      } else if (s.event === "final") {
        const leader = s.seats.reduce((best, seat, i) => (seat.stack > s.seats[best].stack ? i : best), 0);
        log({ kind: "final", seat: leader, text: "takes the table", tone: "win" });
        tell({ seat: leader, text: "takes the table", tone: "win" });      }

      previous = s;
      setSnap(s);
    };

    source.addEventListener("end", () => {
      if (!live) return;
      source.close();
      setTurn(null);
      setConnection("finished");
    });
    source.addEventListener("fatal", (event) => {
      if (!live) return;
      source.close();
      setError(String((event as MessageEvent).data ?? "engine failed to start"));
      setConnection("error");
    });
    source.onerror = () => {
      if (!live) return;
      source.close();
      setConnection((current) => (current === "finished" ? current : "error"));
    };

    return () => {
      live = false;
      source.close();
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [run, lineup, mode]);

  return { snap, turn, actions, feed, story, flights, connection, error };
}
