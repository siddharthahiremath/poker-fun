"use client";

import { useState } from "react";
import { Hud } from "@/components/hud";
import { Feed, Standings } from "@/components/sidebar";
import { Table } from "@/components/table";
import { WinsChart } from "@/components/wins";
import { TIME_DEFAULT, TIME_MAX, TIME_MIN, type Mode } from "@/lib/options";
import { useTable, type Lineup } from "@/lib/use-table";

const LINEUPS: { id: Lineup; label: string }[] = [
  { id: "demo", label: "Demo bots" },
  { id: "real", label: "Submissions" },
];

const MODES: { id: Mode; label: string }[] = [
  { id: "table", label: "Table" },
  { id: "wins", label: "Wins" },
];

export function PokerRoom() {
  const [run, setRun] = useState(0);
  const [lineup, setLineup] = useState<Lineup>("demo");
  const [mode, setMode] = useState<Mode>("table");
  const [timeLimit, setTimeLimit] = useState(TIME_DEFAULT);
  const [draftTime, setDraftTime] = useState(TIME_DEFAULT);
  const appliedTime = mode === "wins" ? TIME_MAX : timeLimit;
  const { snap, turn, actions, feed, story, flights, connection, error } = useTable(run, lineup, appliedTime, mode);
  const restart = () => setRun((value) => value + 1);
  const commitTime = (value: number) => {
    const next = Math.min(TIME_MAX, Math.max(TIME_MIN, Math.round(value)));
    setDraftTime(next);
    setTimeLimit(next);
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-[1520px] flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
      <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
        <h1 className="text-2xl font-medium text-zinc-900">Agent Hold&apos;em</h1>

        <div className="flex flex-wrap items-center gap-3">
          <div role="radiogroup" aria-label="Lineup" className="flex h-9 items-center rounded-lg border border-line bg-panel p-1 text-sm">
            {LINEUPS.map((option) => (
              <button
                key={option.id}
                role="radio"
                aria-checked={lineup === option.id}
                onClick={() => setLineup(option.id)}
                className={`flex h-full items-center rounded px-3 font-medium transition-colors duration-150 ${
                  lineup === option.id
                    ? "bg-zinc-100 text-zinc-900 shadow-[inset_0_0_0_1px_rgba(24,24,27,0.08)]"
                    : "text-zinc-500 hover:text-zinc-900"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div role="radiogroup" aria-label="Mode" className="flex h-9 items-center rounded-lg border border-line bg-panel p-1 text-sm">
            {MODES.map((option) => (
              <button
                key={option.id}
                role="radio"
                aria-checked={mode === option.id}
                onClick={() => setMode(option.id)}
                className={`flex h-full items-center rounded px-3 font-medium transition-colors duration-150 ${
                  mode === option.id
                    ? "bg-zinc-100 text-zinc-900 shadow-[inset_0_0_0_1px_rgba(24,24,27,0.08)]"
                    : "text-zinc-500 hover:text-zinc-900"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          {mode === "table" && (
            <label className="flex h-9 items-center gap-3 text-sm text-zinc-600">
              <span className="w-10 text-right tabular-nums text-zinc-900">{draftTime}s</span>
              <input
                type="range"
                min={TIME_MIN}
                max={TIME_MAX}
                step={1}
                value={draftTime}
                aria-label="Seconds per move"
                onChange={(event) => setDraftTime(Number(event.target.value))}
                onPointerUp={(event) => commitTime(Number(event.currentTarget.value))}
                onKeyUp={(event) => commitTime(Number(event.currentTarget.value))}
                onBlur={(event) => commitTime(Number(event.target.value))}
              />
            </label>
          )}
          <button
            onClick={restart}
            className="inline-flex h-9 items-center rounded-lg bg-zinc-900 px-4 text-sm font-medium text-white transition-[background-color,transform] duration-150 hover:bg-zinc-700 active:scale-[0.98]"
          >
            New game
          </button>
        </div>
      </header>

      {connection === "error" && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span>
            The table stopped{error ? ` (${error})` : ""}. Check that python3 runs from the project folder, then start a new game.
          </span>
          <button onClick={restart} className="font-medium text-red-800 underline underline-offset-4">
            Start a new game
          </button>
        </div>
      )}

      <main className="grid flex-1 gap-x-10 gap-y-10 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="flex min-w-0 flex-col gap-6">
          <Hud snap={snap} turn={turn} story={story} />
          {mode === "wins" ? (
            <WinsChart snap={snap} />
          ) : (
            <Table snap={snap} turn={turn} actions={actions} flights={flights} finished={connection === "finished"} onRestart={restart} />
          )}
        </section>
        <aside className="flex flex-col gap-8 border-line xl:border-l xl:pl-10">
          {mode === "table" && <Standings snap={snap} turn={turn} />}
          <Feed feed={feed} snap={snap} />
        </aside>
      </main>
    </div>
  );
}
