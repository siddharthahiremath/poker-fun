import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { readTime, TIME_MAX, type Mode } from "@/lib/options";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const LINEUPS: Record<string, string> = { demo: "demo_agents", real: "agents" };
const IDLE_KILL_MS = 15_000;
// the dev server doesn't report disconnects, so a viewer whose stream stops being read counts as gone
const UNREAD_LIMIT = 200;

type Viewer = (message: string) => boolean;
type Game = {
  lineup: string;
  timeLimit: number;
  mode: Mode;
  child: ChildProcess;
  last: string | null;
  viewers: Set<Viewer>;
  done: boolean;
  idleTimer?: ReturnType<typeof setTimeout>;
};

// one shared table per server, kept on globalThis so dev reloads don't orphan the engine
const shared = globalThis as unknown as { pokerGame?: Game };

function broadcast(game: Game, message: string) {
  for (const viewer of game.viewers) {
    let ok = false;
    try {
      ok = viewer(message);
    } catch {}
    if (!ok) game.viewers.delete(viewer);
  }
  watchIdle(game);
}

function watchIdle(game: Game) {
  if (game.viewers.size > 0 || game.done) {
    clearTimeout(game.idleTimer);
    game.idleTimer = undefined;
  } else if (!game.idleTimer) {
    game.idleTimer = setTimeout(() => game.viewers.size === 0 && game.child.kill(), IDLE_KILL_MS);
  }
}

function startGame(lineup: string, timeLimit: number, mode: Mode) {
  const previous = shared.pokerGame;
  const viewers = previous?.viewers ?? new Set<Viewer>();
  if (previous) {
    previous.viewers = new Set();
    previous.done = true;
    clearTimeout(previous.idleTimer);
    previous.child.kill();
  }

  const args = ["-u", "poker.py", "--agents", LINEUPS[lineup], "--json", "--time", String(timeLimit)];
  if (mode === "wins") args.push("--wins");
  const child = spawn(process.env.PYTHON ?? "python3", args, {
    cwd: path.resolve(process.cwd(), ".."),
    stdio: ["ignore", "pipe", "inherit"],
  });
  const game: Game = { lineup, timeLimit, mode, child, last: null, viewers, done: false };
  shared.pokerGame = game;
  broadcast(game, "event: reset\ndata: {}\n\n");

  let buffer = "";
  child.stdout?.setEncoding("utf8");
  child.stdout?.on("data", (chunk: string) => {
    buffer += chunk;
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line.startsWith("{")) {
        game.last = line;
        broadcast(game, `data: ${line}\n\n`);
      }
      newline = buffer.indexOf("\n");
    }
  });
  child.on("close", (code) => {
    if (game.done) return;
    game.done = true;
    broadcast(game, `event: end\ndata: ${code ?? 0}\n\n`);
  });
  child.on("error", (error) => {
    game.done = true;
    broadcast(game, `event: fatal\ndata: ${JSON.stringify(error.message)}\n\n`);
  });
  return game;
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const lineup = LINEUPS[params.get("lineup") ?? ""] ? params.get("lineup")! : "demo";
  const timeLimit = params.get("mode") === "wins" ? TIME_MAX : readTime(params.get("time"));
  const mode: Mode = params.get("mode") === "wins" ? "wins" : "table";
  const current = shared.pokerGame;
  const game =
    !current ||
    current.done ||
    current.lineup !== lineup ||
    current.timeLimit !== timeLimit ||
    current.mode !== mode ||
    params.get("restart") === "1"
      ? startGame(lineup, timeLimit, mode)
      : current;

  const encoder = new TextEncoder();
  let viewer: Viewer | null = null;
  const leave = () => {
    if (viewer) game.viewers.delete(viewer);
    watchIdle(game);
  };

  const stream = new ReadableStream({
    start(controller) {
      let open = true;
      viewer = (message) => {
        if (!open) return false;
        // throws when the browser already closed the stream; broadcast drops the viewer
        if ((controller.desiredSize ?? 0) < -UNREAD_LIMIT) {
          open = false;
          controller.close();
          return false;
        }
        controller.enqueue(encoder.encode(message));
        if (message.startsWith("event: end") || message.startsWith("event: fatal")) {
          open = false;
          controller.close();
          return false;
        }
        return true;
      };
      if (game.last) viewer(`data: ${game.last}\n\n`);
      if (game.done) viewer("event: end\ndata: 0\n\n");
      else game.viewers.add(viewer);
      watchIdle(game);
      request.signal.addEventListener("abort", leave);
    },
    cancel: leave,
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
