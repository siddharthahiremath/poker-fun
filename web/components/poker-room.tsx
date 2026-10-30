"use client";

import { useState } from "react";
import { Hud } from "@/components/hud";
import { Pace } from "@/components/pieces";
import { Feed, Standings } from "@/components/sidebar";
import { Table } from "@/components/table";
import { WinsChart } from "@/components/wins";
import { formatSeconds, readTime, TIME_DEFAULT, TIME_MAX, TIME_MIN, type Mode, type TimeWhen } from "@/lib/options";
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
  const [draftTime, setDraftTime] = useState(formatSeconds(TIME_DEFAULT));
  const [when, setWhen] = useState<TimeWhen>("hand");
  const { snap, turn, actions, feed, story, flights, connection, error } = useTable(run, lineup, timeLimit, mode);
  const fast = (snap?.time_limit ?? timeLimit) < 1;
  const restart = () => setRun((value) => value + 1);
  const applyTime = (raw: string, nextWhen: TimeWhen = when) => {
    const next = readTime(raw);
    setDraftTime(formatSeconds(next));
    setTimeLimit(next);
    setWhen(nextWhen);
    void fetch("/api/game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time: next, when: nextWhen }),
    });
  };

  return (
    <Pace.Provider value={fast}>
    <div className={`mx-auto flex min-h-screen max-w-[1520px] flex-col gap-8 px-4 py-6 sm:px-6 lg:px-10 lg:py-8 ${fast ? "fast" : ""}`}>
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
          <div className="flex h-9 items-center gap-2 text-sm">
              <label className="flex h-9 items-center gap-2 rounded-lg border border-line bg-panel px-3 text-zinc-600">
                <input
                  type="number"
                  inputMode="decimal"
                  min={TIME_MIN}
                  max={TIME_MAX}
                  step="any"
                  value={draftTime}
                  aria-label="Seconds per move"
                  onChange={(event) => setDraftTime(event.target.value)}
                  onBlur={(event) => applyTime(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      applyTime(event.currentTarget.value);
                    }
                  }}
                  className="w-16 bg-transparent text-right tabular-nums text-zinc-900 outline-none"
                />
                <span>s</span>
              </label>
              <div role="radiogroup" aria-label="When the time limit changes" className="flex h-9 items-center rounded-lg border border-line bg-panel p-1">
                {([
                  ["now", "Now"],
                  ["hand", "Next hand"],
                ] as const).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={when === id}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => applyTime(draftTime, id)}
                    className={`flex h-full items-center rounded px-3 font-medium transition-colors duration-150 ${
                      when === id
                        ? "bg-zinc-100 text-zinc-900 shadow-[inset_0_0_0_1px_rgba(24,24,27,0.08)]"
                        : "text-zinc-500 hover:text-zinc-900"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
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
    </Pace.Provider>
  );
}
