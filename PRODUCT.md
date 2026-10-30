# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A group of friends who each write a poker bot and enter it in a shared Texas hold'em tournament.

- **Game night, together:** the group watches one live table on a shared screen, projector, or stream. The table is the event.
- **Solo, between games:** each friend watches on their own laptop or phone to see how their bot plays, why it won or lost a hand, and whether it is timing out or making illegal moves.

## Product Purpose

Agent Hold'em runs a no-limit hold'em game between friends' bots and lets anyone watch it live. Success means bots play every hand to completion without the engine crashing, and watchers can follow every decision as it happens: who acted, what they did, how long they took, and what they held.

## Positioning

It is a private arena for one friend group, not a public bot ladder. Watchers see everything, including every hole card and each bot's think time, so the table is part spectator sport and part debugging view.

## Operating Context

- Each friend submits one Python file to `agents/`. Files that start with `_` or `template` are skipped. `agents/template.py` is the reference random bot.
- `poker.py` is the engine. `python3 poker.py` runs a quick game in the terminal. `--json` streams one table snapshot per line, and `--agents DIR` chooses the lineup folder.
- `web/` is a Next.js spectator app. `/api/game` runs one shared engine process and streams it to every viewer over server-sent events. The UI switches between the demo bots in `demo_agents/` and real submissions in `agents/`.
- The demo bots in `demo_agents/` play randomly with different temperaments and stand in until real submissions arrive.

## Capabilities and Constraints

- **Submissions:** one Python file per friend, placed in `agents/`.
- **Time limit:** 10 seconds per move, and agents receive the limit in their view. A timeout or invalid reply checks if checking is legal and folds otherwise.
- **Robustness:** the engine must never crash on a hostile or broken agent, whether it hangs, throws, exits, prints, or returns junk. Malformed replies are rejected by exact type.
- **Full information for agents:** each turn passes the seat, street, hole cards, board, pot, all stacks, bets, legal actions, min and max raise amounts, button, blinds, and hand history.
- **Full information for spectators:** every agent's hole cards are visible at all times, along with each live player's chance to win the hand. Odds are exact from the flop on and sampled before it.
- **Blinds:** start at 5/10 and double every 3 hands, so games always end.
- **Trust model:** agents run in the engine's own process with no sandbox, because friends are trusted. A determined cheater could read memory or hog the CPU. Real isolation would need subprocesses.
- **Rules:** standard no-limit hold'em with min-raise rules, side pots, and a short all-in that does not reopen raising.
- **Tournament format:** currently a single freezeout where the last bot with chips wins. A fuller multi-stage format exists in the owner's plans but is not specified here yet.
- **Environment:** the owner's machine runs Node 18, so Tailwind is pinned to 4.1.x.

## Brand Commitments

The product name is "Agent Hold'em". The tone is casual, like a game among friends.

## Evidence on Hand

- Six demo bots in `demo_agents/`: maverick, ghost, sloth, viper, oracle, and tilt.
- No real friend submissions yet. No match results, standings history, or player profiles exist, so future work must not invent them.

## Product Principles

1. **The engine never falls over.** Any agent behavior, however broken, ends in a legal action or a fold, never a crash.
2. **Show everything, and say what it means.** Cards, odds, think time, timeouts, and every action are visible and narrated in plain words, because watching and debugging are the same activity here.
3. **One table, everyone watching.** A single shared game is the event. Viewers join it rather than each starting their own.
4. **Submitting stays trivial.** One file, one function, and a documented view of the game state. The template has to stay simple.
5. **It works on a big screen and on a phone.** Desktop comes first for game night, and the phone has to stay readable for solo checking.
