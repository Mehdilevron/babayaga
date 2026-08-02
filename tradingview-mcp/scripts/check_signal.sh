#!/usr/bin/env bash
# Runs a one-shot top-down ICT/Smart Money Concepts analysis via the Claude
# Code CLI against the tradingview-mcp tools, and pushes an ntfy.sh
# notification when a confirmed 4-step ICT entry is found:
#   1. Liquidity sweep
#   2. Higher-timeframe FVG aligned with the move
#   3. CISD (Change In State Of Delivery) confirming the reversal
#   4. iFVG on 5m/1m: a FVG inverted by price, then tapped/reacted to
#
# This performs technical chart-pattern analysis only. It does not place
# trades and is not financial advice -- verify any signal yourself.
set -uo pipefail

# Required: pick your own topic name, don't reuse one from documentation --
# anyone who knows a public ntfy.sh topic name can read messages sent to it.
#   export NTFY_TOPIC=my-own-random-slug
: "${NTFY_TOPIC:?Set NTFY_TOPIC to a topic name you chose yourself, e.g. export NTFY_TOPIC=my-own-random-slug}"

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
# Name the MCP server was registered under (see README "Automated alerts").
# Use a *separate* registration from your interactive one, with
# TRADINGVIEW_MCP_NO_OPEN=1 set, so this doesn't pop a browser tab every run.
MCP_SERVER_NAME="${MCP_SERVER_NAME:-tradingview-bg}"
SYMBOL="${SYMBOL:-BTCUSDT}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/signal_check.log}"

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }

if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "$(timestamp) claude CLI not found at '$CLAUDE_BIN'" >> "$LOG_FILE"
  exit 0
fi

PROMPT=$(cat <<PROMPT_EOF
Using the tradingview-mcp tools, perform a top-down ICT analysis on $SYMBOL
using this exact 4-step entry model. Call chart_set_symbol first to load the
symbol, then call chart_clear_shapes to remove any shapes from previous runs,
then follow these steps in order:

STEP 1 -- HIGHER TIMEFRAME BIAS AND LIQUIDITY TARGET:
chart_set_timeframe to "4h", then data_get_ohlcv. Identify the dominant
bias (bullish or bearish) and the most obvious liquidity pool being targeted
-- equal highs (Buy Side Liquidity, BSL) for a bearish move, or equal lows
(Sell Side Liquidity, SSL) for a bullish move. Identify the 4h Fair Value
Gap (FVG) aligned with that bias: a 3-candle imbalance where the gap between
candle 1 and candle 3 was not overlapped by the middle candle. Draw the 4h
FVG as a rectangle: draw_shape type "rectangle", priceHigh and priceLow set
to the FVG boundaries, color "green" for a bullish FVG or "red" for a
bearish FVG, label "4h FVG". Then chart_set_timeframe to "1h", data_get_ohlcv,
and confirm or refine the liquidity pool price. Draw it: draw_shape type
"line", color "white", label "Liquidity Target", and that price.

STEP 2 -- LIQUIDITY SWEEP (15m):
chart_set_timeframe to "15m", then data_get_ohlcv. Determine whether price
has swept through the liquidity pool in recent candles -- a wick or close
beyond the equal highs or equal lows. If a sweep has occurred, record the
exact wick extreme price of the sweep. Draw it: draw_shape type "line",
color "orange", label "Sweep", and that price. If no sweep has occurred,
set signal to NONE and stop -- do not proceed to Steps 3 or 4.

STEP 3 -- CISD (Change In State Of Delivery, 15m):
Still on the 15m chart (same data_get_ohlcv result is sufficient). After the
sweep candle, look for a CISD candle: a candle that closes BEYOND the HIGH of
the previous candle (for a bullish reversal after a bearish/SSL sweep) or
BEYOND the LOW of the previous candle (for a bearish reversal after a
bullish/BSL sweep). This candle confirms that price has changed its delivery
direction. Record the exact close price of the CISD candle. Draw it:
draw_shape type "line", color "yellow", label "CISD". If no CISD candle is
present after the sweep on the 15m chart, set signal to NONE and stop.

STEP 4 -- iFVG TAP AND ENTRY (5m, or 1m if 5m is unclear):
chart_set_timeframe to "5m", then data_get_ohlcv. After the CISD, look for
a Fair Value Gap (FVG) that price has since traded back through completely
from the opposite side -- this inverts the FVG into an Inversion FVG (iFVG).
A bullish FVG inverted by price trading down through it becomes a bearish
iFVG (now acts as resistance). A bearish FVG inverted by price trading up
through it becomes a bullish iFVG (now acts as support). Record the exact
high and low boundaries of the iFVG zone. Draw it: draw_shape type
"rectangle", priceHigh and priceLow set to the iFVG boundaries, color "red"
for a bearish iFVG or "green" for a bullish iFVG, label "iFVG". Then
determine: has price subsequently tapped this iFVG zone (returned to it) and
shown a reaction (a rejection candle, a momentum candle moving away from the
zone, or a clear stall at the zone boundary)? If unclear on 5m, repeat the
same check on "1m". If price has tapped and reacted to the iFVG, that is the
entry trigger -- finalize the signal. If the iFVG has not yet been tapped,
set signal to NONE (setup is forming, wait for the tap).

STEP 5 -- TARGET (only if signaling BUY or SELL):
The target is the far boundary of the 4h FVG identified in Step 1, or the
next significant liquidity pool beyond it in the trade direction, whichever
comes first. Draw it: draw_shape type "line", color "blue", label "Target".

Respond with ONLY a single-line JSON object, no other text, no markdown
fences, with these exact keys:
{"signal": "BUY", "symbol": "...", "liquidity_target": 0.0,
"htf_fvg_zone": "0.0-0.0", "sweep_price": 0.0, "cisd_price": 0.0,
"ifvg_zone": "0.0-0.0", "ifvg_reacted": true, "entry_timeframe": "5m",
"target_price": 0.0, "reason": "..."}
Use the same keys for SELL. For NONE, set numeric fields to null, booleans
to false, and explain which step failed (and why) in reason.
PROMPT_EOF
)

TOOL_PREFIX="mcp__${MCP_SERVER_NAME}__"
RAW_OUTPUT=$("$CLAUDE_BIN" -p \
  --allowedTools "${TOOL_PREFIX}chart_set_symbol" "${TOOL_PREFIX}chart_set_timeframe" "${TOOL_PREFIX}data_get_ohlcv" "${TOOL_PREFIX}quote_get" "${TOOL_PREFIX}draw_shape" "${TOOL_PREFIX}chart_get_state" "${TOOL_PREFIX}chart_clear_shapes" \
  --output-format json \
  --max-turns 60 \
  "$PROMPT" 2>>"$LOG_FILE")
STATUS=$?

if [ $STATUS -ne 0 ] || [ -z "$RAW_OUTPUT" ]; then
  echo "$(timestamp) claude invocation failed (exit $STATUS)" >> "$LOG_FILE"
  exit 0
fi

PARSED=$(RAW_OUTPUT="$RAW_OUTPUT" python3 -c '
import json, os, sys
try:
    outer = json.loads(os.environ["RAW_OUTPUT"])
    text = outer.get("result", "")
    start = text.find("{")
    end = text.rfind("}")
    inner = json.loads(text[start:end+1])
    fields = [
        str(inner.get("signal") or "NONE"),
        str(inner.get("symbol") or ""),
        str(inner.get("liquidity_target") if inner.get("liquidity_target") is not None else ""),
        str(inner.get("htf_fvg_zone") if inner.get("htf_fvg_zone") is not None else ""),
        str(inner.get("sweep_price") if inner.get("sweep_price") is not None else ""),
        str(inner.get("cisd_price") if inner.get("cisd_price") is not None else ""),
        str(inner.get("ifvg_zone") if inner.get("ifvg_zone") is not None else ""),
        str(inner.get("ifvg_reacted") if inner.get("ifvg_reacted") is not None else ""),
        str(inner.get("entry_timeframe") or ""),
        str(inner.get("target_price") if inner.get("target_price") is not None else ""),
        str(inner.get("reason") or ""),
    ]
    print("|".join(fields))
except Exception:
    print("|".join(["NONE","","","","","","","","","","parse-error"]))
')

IFS='|' read -r SIGNAL SYMBOL_OUT LIQUIDITY_TARGET HTF_FVG_ZONE SWEEP_PRICE CISD_PRICE IFVG_ZONE IFVG_REACTED ENTRY_TF TARGET_PRICE REASON <<< "$PARSED"

echo "$(timestamp) signal=$SIGNAL symbol=$SYMBOL_OUT liq_target=$LIQUIDITY_TARGET htf_fvg=$HTF_FVG_ZONE sweep=$SWEEP_PRICE cisd=$CISD_PRICE ifvg=$IFVG_ZONE ifvg_reacted=$IFVG_REACTED entry_tf=$ENTRY_TF target=$TARGET_PRICE reason=$REASON" >> "$LOG_FILE"

if [ "$REASON" = "parse-error" ]; then
  echo "$(timestamp) parse-error raw claude output (first 2000 chars): $(printf '%s' "$RAW_OUTPUT" | head -c 2000)" >> "$LOG_FILE"
fi

if [ "$SIGNAL" = "BUY" ] || [ "$SIGNAL" = "SELL" ]; then
  MESSAGE=$(printf "Liq Target: %s | HTF FVG: %s\nSweep: %s | CISD: %s\niFVG zone: %s (reacted: %s)\nEntry on: %s | Target: %s\n\n%s" \
    "$LIQUIDITY_TARGET" "$HTF_FVG_ZONE" "$SWEEP_PRICE" "$CISD_PRICE" \
    "$IFVG_ZONE" "$IFVG_REACTED" "$ENTRY_TF" "$TARGET_PRICE" "$REASON")
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Title: ICT Signal: $SIGNAL $SYMBOL_OUT" \
    -H "Priority: high" \
    -H "Tags: chart_increasing" \
    --data-binary "$MESSAGE" \
    "https://ntfy.sh/$NTFY_TOPIC")
  echo "$(timestamp) ntfy push to topic=$NTFY_TOPIC http_status=$HTTP_STATUS" >> "$LOG_FILE"
fi
