#!/bin/sh
# Runs agents/sid.py through a fixed set of matchups and prints its win rate in each.
# usage: sh bench/suite.sh [games] [time]
cd "$(dirname "$0")/.."
GAMES=${1:-1200}
TIME=${2:-0.01}
run() {
  label=$1; shift
  printf "%-10s " "$label"
  python3 bench/arena.py --time "$TIME" --games "$GAMES" agents/sid.py "$@" 2>/dev/null | grep " sid " | awk '{print $3}'
}
run allin bench/bots/allin.py
run station bench/bots/station.py
run viper demo_agents/viper.py
run tag bench/bots/tag.py
run eqbot bench/bots/eqbot.py
run demo7 demo_agents/*.py
run mixed7 bench/bots/allin.py bench/bots/station.py bench/bots/rock.py bench/bots/tag.py demo_agents/maverick.py demo_agents/tilt.py
run friends7 bench/bots/eqbot.py bench/bots/eqbot.py bench/bots/tag.py bench/bots/allin.py bench/bots/station.py demo_agents/maverick.py
