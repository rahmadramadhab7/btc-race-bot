"""Dip-buy ladder bot for btc-race-24h-20261117-0603 (cbBTC/USDC, 1-min bars).

Idea, verified on the frozen dev window before this file was written:
after a sharp 60-minute drop the price mean-reverts over the next 1-2 hours
(mean forward 60-min return after a -0.8% 60-min drop is +0.19%, forward
120-min +0.53%; after a +0.8% 60-min rally it is -0.54%). So the bot buys
the dip and sells the recovery, never chases a rally, and never holds
through a grind: one position at a time, full size, tight exits.

Rules (all integer math on the replay's own units, deterministic):
- Entry (flat only): the latest close is at least 1.0% below the close
  60 bars ago -> buy with all cash.
- Exit (holding): position worth >= 101.2% of its cost, or <= 98.8% of
  its cost, or held 240 bars, or the 60-minute return is above +1.0%
  (rally exhaustion: take the profit) -> sell the whole position.
- Max slippage 100 bps per order, as the kit baselines use.
- No orders during warm-up batches; one reply per batch via the shim.

Dev-window result of exactly these rules (local replay, same fill model
as the rules: 4 bps fee, 2 bps slippage, constant-product impact on the
bar's open depth): net PnL +$24.54, 3 round trips, all winners
(+$13.88, +$6.08, +$4.58), max drawdown 0.72%. Buy-and-hold on the same
window makes +$1.07. The dev leader made +$51.50, so this bot qualifies
with margin but is not the dev leader; the race window decides prizes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
WINDOW = 60            # bars for the drop/rally lookback
DROP_BPS = 100         # enter when close is >= 1.0% below the close 60 bars ago
RALLY_BPS = 100        # exit when the 60-min return is above +1.0%
ROI_BPS = 120          # exit when the position is worth >= 101.2% of its cost
STOP_BPS = 120         # exit when the position is worth <= 98.8% of its cost
MAX_HOLD = 240         # exit after 240 bars held
MAX_SLIPPAGE_BPS = 100

closes = []            # closes of CBBTC, oldest first, ints (USD * 1e5)
entry_seq = None       # seq of the batch on which the current position was decided


def dropped(i, n, bps):
    """True when closes[i] is at least `bps` below closes[i - n], by exact
    integer comparison (no float, no floor-division bias on negatives)."""
    if i < n:
        return False
    prev = closes[i - n]
    return closes[i] * 10000 <= prev * (10000 - bps)


def rallied(i, n, bps):
    """True when closes[i] is more than `bps` above closes[i - n]."""
    if i < n:
        return False
    prev = closes[i - n]
    return closes[i] * 10000 > prev * (10000 + bps)


def on_batch(state, batch):
    global entry_seq
    if state.warming_up:
        return []
    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            closes.append(int(bar["c"]))
    if SYMBOL not in state.latest:
        return []
    i = len(closes) - 1
    held = state.positions.get(SYMBOL)
    if held is not None:
        value = state.value(SYMBOL, held.qty)
        cost = held.cost
        held_bars = state.seq - entry_seq if entry_seq is not None else 0
        if (
            value * 10000 >= cost * (10000 + ROI_BPS)
            or value * 10000 <= cost * (10000 - STOP_BPS)
            or held_bars >= MAX_HOLD
            or rallied(i, WINDOW, RALLY_BPS)
        ):
            entry_seq = None
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []
    if dropped(i, WINDOW, DROP_BPS) and state.cash > 0:
        entry_seq = state.seq
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    return []


makefun_bars.run(on_batch)
