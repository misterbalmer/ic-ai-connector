# ma_stack_4h — Engineering Spec

## Purpose

Add one new object per symbol to the Konsole snapshot, computed from the existing 1000-bar 4H series already available. Gives the trading agent a numeric read of EMA stack alignment, trend durability, and pullback depth — replacing what a human currently gets by eyeballing the chart.

## Inputs (per symbol, from existing 4H series)

- `close[]` — 4H close prices, at least 1000 bars
- EMA periods: 21, 50, 200 (standard EMA, not SMA — confirm with whoever owns the existing 4H/SMA200 calc whether to reuse SMA200 or add a new EMA200; see Note A below)

## Output shape

```json
"ma_stack_4h": {
  "trend_score": 1.0,
  "ema200_slope_positive": true,
  "price_vs_21": -0.6,
  "price_vs_50": 1.8,
  "price_vs_200": 8.4,
  "bars_since_stack_aligned": 4,
  "bars_since_price_below_ema21": 0
}
```

## Field-by-field computation

### 1. `ema_21`, `ema_50`, `ema_200` (internal — used to derive the fields below, do not need to ship raw values unless useful for debugging)

Standard EMA on `close[]`, periods 21 / 50 / 200. Standard recursive EMA formula, seeded with SMA of the first N bars.

### 2. `trend_score` (float, 0.0–1.0)

Four binary checks, averaged. This mirrors a standard regime-score pattern (close-vs-MA, close-vs-MA, MA-vs-MA ordering):

```
c1 = close[now] > ema_21  ? 1 : 0
c2 = close[now] > ema_50  ? 1 : 0
c3 = ema_21 > ema_50       ? 1 : 0
c4 = ema_50 > ema_200      ? 1 : 0

trend_score = (c1 + c2 + c3 + c4) / 4.0
```

`1.0` = textbook bullish stack, price above all three, all in order. `0.0` = fully inverted/bearish. Values in between tell you partial alignment (e.g. price below 21 but stack otherwise bullish = pullback in trend).

### 3. `ema200_slope_positive` (boolean)

Is the long MA itself still rising, not just is price above it.

```
ema200_slope_positive = ema_200[now] > ema_200[5 bars ago]
```

Use 5 bars (= 20 hours) as the lookback; this matches existing conventions elsewhere in the system. Confirm with the team if a different lookback is preferred — longer lookback = less noisy but slower to flip.

### 4. `price_vs_21`, `price_vs_50`, `price_vs_200` (float, signed percent)

Distance of current close from each EMA, as a signed percentage. Negative = price below that EMA.

```
price_vs_X = (close[now] - ema_X) / ema_X * 100
```

### 5. `bars_since_stack_aligned` (integer)

How many consecutive bars (walking backward from now) has the bullish order held: `ema_21 > ema_50 > ema_200`. Caps out — see Note B.

```
count = 0
for i in range(0, max_lookback):
    if ema_21[now-i] > ema_50[now-i] > ema_200[now-i]:
        count += 1
    else:
        break
bars_since_stack_aligned = count
```

If the stack is NOT currently aligned (i.e. count would be 0 on the current bar), return `0`.

### 6. `bars_since_price_below_ema21` (integer)

How many consecutive bars since price last closed below EMA_21. Tells you whether there's been any pullback yet since the last leg up.

```
count = 0
for i in range(0, max_lookback):
    if close[now-i] > ema_21[now-i]:
        count += 1
    else:
        break
bars_since_price_below_ema21 = count
```

`0` means price is currently below EMA_21 right now (i.e. a pullback is actively happening).

## Note A — EMA200 vs existing SMA200

The existing Konsole 4H column and trade_engine fields use SMA200 for the "trend strength" / energy calculations. This spec uses EMA200 for `ema_stack_4h` because EMA is what's conventionally used for stacked-MA reads. **Confirm with the team**: it's fine to have both (SMA200 for the energy/σ system, EMA200 for the new stack system) — they answer different questions — but make sure naming in the codebase doesn't let them get confused with each other (e.g. don't call a variable just `sma200` in one place and `ema200` in another without a clear comment).

## Note B — lookback cap and warm-up

- EMA_200 needs ~200+ bars of history before it's meaningful; with 1000 bars available this is not a constraint.
- Cap `bars_since_stack_aligned` and `bars_since_price_below_ema21` at some max (suggest 200 bars) purely so the loop doesn't run unbounded on symbols that have been perfectly aligned for the entire history window. Anything past ~50 bars (≈8 days on 4H) already reads as "long-established," so capping at 200 loses no decision-relevant information.
- If fewer than 200 bars of 4H history exist for a symbol (new listing), return `null` for the whole `ma_stack_4h` object rather than computing on insufficient data — same pattern likely already used elsewhere for "insufficient history" (e.g. σ requires ~50 samples, 4H trend strength requires ~219 bars).

## Edge cases to test against

1. **Symbol with no trend history (flat, dead price for most of the 1000 bars), then a single violent wick.** `bars_since_stack_aligned` should be very low (1-3) immediately after the wick, even if `trend_score` reads 1.0. This is the "don't chase the first impulse" case.
2. **Symbol in a long, orderly basing/trend after an initial spike has cooled.** `bars_since_stack_aligned` should be high (30+) — this is the "established, trust the alignment" case.
3. **Symbol mid-pullback, stack still bullish but price dipped below EMA_21.** `trend_score` should drop to ~0.75 (loses the `c1` point only), `bars_since_price_below_ema21` should be `0`, `price_vs_21` should be negative while `price_vs_50`/`price_vs_200` stay positive.
4. **Symbol in a clean downtrend (stack fully inverted).** `trend_score` near 0.0, `ema200_slope_positive` false, all `price_vs_X` negative.

## What this does NOT need to do

- Does not need to output a categorical label like `"pullback_starting"` or `"strong_trend"` — the agent derives that conclusion itself from the numeric fields. Do not add a derived-label field; keep this layer purely numeric. (This mirrors a past lesson: a similarly-named extension/energy field was previously misread by the LLM consuming it, and the fix was clearer raw fields + explicit documentation, not a smarter label.)
- Does not need to replace or modify the existing σ / energy_z / 4H trend-strength fields — those answer a different question (how statistically extreme is the current SMA200 deviation vs this symbol's own history) and should stay untouched.

## Delivery (implemented)

| Item | Choice |
|------|--------|
| Consumer | AI agent only — `universe[].ma_stack_4h` on egress POST |
| Konsole UI | Not shown; not attached to `konsole_grid` IPC rows |
| Recompute | `KonsoleMaintWake::Energy4h` → `load_energy_baselines` (same 4H klines pull as energy/structure) |
| Cache | `konsole_ma_stack::global_ma_stack_cache()` keyed by asset label; sync read in `egress_connector::project_row` |
| Min history | 200 closed 4H bars; compute on full pull (up to 1000 bars) for slope and `bars_since_*` |
| EMA source | Shared `konsole_macro::ema_series` (EMA21/50/200; distinct from SMA200 energy system) |
