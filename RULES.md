# Rules

This is how Agent Hold'em actually plays. The engine in `poker.py` is the source of truth.

## The game

No-limit Texas hold'em. One standard 52-card deck, shuffled every hand. There are no burn cards. Each seat gets two hole cards. The board is dealt three, then one, then one: flop, turn, river.

Up to 22 seats. A lineup is every `*.py` file in the agents folder except names that start with `_` or `template`. If fewer than two files are there, `template.py` fills the empty seats.

## Hand rankings

Best five cards, using the hole cards and the board. Highest category wins. Ties break on the kickers in the order the engine scores them.

1. Straight flush
2. Four of a kind
3. Full house
4. Flush
5. Straight
6. Three of a kind
7. Two pair
8. Pair
9. High card

Ace plays high, except in the wheel (A-2-3-4-5), where it plays low and that straight is the lowest straight. Suits never break a tie.

## A hand

The button moves to the next seat that still has chips.

Blinds are posted before any cards are bet on. With three or more players, the small blind is the next occupied seat left of the button, and the big blind is the next one after that. Heads-up, the button posts the small blind and the other player posts the big blind.

Preflop, the first player to act is the next seat left of the big blind. On the flop, turn, and river, the first player to act is the next occupied seat left of the button. A seat that is all-in or folded does not act.

A street ends when every player who can still act has matched the current bet and has acted since the last full raise, or when only one player remains in the hand. If everyone else folds, the last player takes the pot without a showdown. If two or more players remain after the river, they show down.

## Betting

Chips bet in a hand stay in the pot. A player may fold, check, call, bet, or raise, and only when that action is in `legal_actions`.

- Check is legal when nothing is owed.
- Call puts in what is owed, or the rest of the stack if it is shorter.
- Bet and raise amounts are the seat's **total chips in on this street** after the action, not the size of the extra chips.
- The minimum bet is the big blind.
- The minimum raise is the size of the previous full bet or raise, and at least the big blind on the first bet of a street.
- A player may always go all-in for the rest of their stack.
- An all-in that raises by less than a full raise does not reopen betting. Players who had already acted cannot raise again. Players who have not acted yet still can.

## The pot

The pot is split into layers equal to what each player put in, so an all-in player can only win what they covered. Each layer goes to the best hand still eligible for it. If several players tie, the layer is split evenly. A leftover chip goes to the winner closest to the left of the button.

Folded players are not eligible. If nobody shows down, the last player in the hand wins every layer they are eligible for.

## One tournament

Every seat starts with 1,000 chips. Blinds start at 5/10 and double every 3 hands. They stop doubling once they reach 20,480/40,960, so a stuck table still ends.

A player with no chips is out and is dealt no further cards. The tournament ends when only one seat has chips. That seat wins the game. If the hand cap is hit first (1,000 hands while the viewer is attached, 20 hands from a plain terminal run), the chip leader wins.

Table mode plays one tournament and then stops.

## Wins mode

Wins mode plays that same freezeout, then sits everyone back at 1,000 and plays another. It does not count hands. A bar goes up only when an agent wins a whole game, meaning they are the last one with chips.

The race keeps going. There is no final table and no rebuy in the middle of a game.

## Time

Each move has a limit, from 0.001 seconds to 30 seconds. The default is 10. The limit is in the info dict as `time_limit`.

The number in the header is seconds per move. It applies in Table mode and in Wins mode.

- **Now** changes the limit immediately, including a move that is already running. A shorter limit can time that move out.
- **Next hand** finishes the current hand on the old limit. The new limit starts with the next hand. The header shows the pending number until then.

Under one second, the viewer drops its pauses and animations. In Wins mode it also stops sending every action and only reports each finished game, so a full tournament can complete as fast as the agents return.

A move that exceeds the limit, throws, or returns something illegal checks if a check is legal and folds otherwise. Loading an agent that fails to come up within 10 seconds sits that seat out for the session.

## What an agent returns

`agents/template.py` is the contract. A file defines `class Agent` with `decide(info)`.

`decide` returns `{"action": "fold" | "check" | "call" | "bet" | "raise", "amount": int}`. `amount` matters for bet and raise, and it is the street total described above. The reply has to be a real dict of plain strings and ints. Anything else is illegal.

`info` contains the seat index, street, hole cards, board, pot, that seat's stack, every stack, every street bet, the amount to call, the minimum bet, the minimum and maximum legal raise-to, the legal actions, who has folded, the button, the blinds, the time limit, and the hand history.

`hand_over(result)` is optional. After a hand, when the move limit is at least one second, the engine may call it with the board, who won what, the stacks, the shown cards, and the history. A slow or broken `hand_over` is ignored.

Agents run inside the engine process. They are trusted. Printing is fine. Hanging, throwing, and returning junk are not allowed to stop the table.

## Watching

One game is shared by everyone looking at the page. Changing the lineup, the mode, or starting a new game restarts that shared game.

Hole cards are face up for the audience the whole time. While a move limit is at least one second, the table also shows each live player's chance to win the hand: exact once the board is far enough along, sampled before the flop.

The action feed is the same sequence the engine played. A duration on a line is how long that move took to come back. A missing duration means the viewer joined in the middle of the move.
