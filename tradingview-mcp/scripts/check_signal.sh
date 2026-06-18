#!/usr/bin/env bash
# Runs a one-shot top-down ICT/Smart Money Concepts analysis via the Claude
# Code CLI against the tradingview-mcp tools, and pushes an ntfy.sh
# notification if a BUY/SELL signal with lower-timeframe entry confirmation
# is found. Designed to be run periodically (cron/launchd/Task Scheduler) on
# a machine that has the `claude` CLI and this MCP server configured.
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
Using the tradingview-mcp tools, perform a top-down ICT/Smart Money Concepts
analysis on $SYMBOL. Call chart_set_symbol first to load it, then follow
these steps in order:
1. chart_set_timeframe to "4h", then data_get_ohlcv, and identify the single
   most important key level (a major untested swing high/low or
   support/resistance). Record its exact price.
2. chart_set_timeframe to "1h", then data_get_ohlcv, and identify the most
   significant liquidity magnet near that key level (equal highs/lows, an
   obvious resting-stop zone). Record its exact price.
3. chart_set_timeframe to "30m", then data_get_ohlcv, to confirm or refine
   that liquidity magnet price.
4. chart_set_timeframe to "15m", then data_get_ohlcv, and determine: (a) has
   price swept through the liquidity magnet in recent candles -- if so
   record the EXACT price of that sweep (the wick extreme that took the
   liquidity), and (b) if so, has an inversion Fair Value Gap formed after
   that sweep (a FVG that price broke back through, flipping its role from
   support to resistance or vice versa) -- if so record the EXACT low/high
   boundaries of that FVG, and whether it has since been mitigated (price
   has fully filled and closed beyond the zone).
5. If an inversion FVG was found, call draw_shape with type "rectangle",
   priceHigh/priceLow set to the FVG boundaries, color red if it is a
   bearish inversion FVG, green if bullish, or gray if mitigated, and a
   short label.
6. Only proceed toward a BUY/SELL signal if BOTH a liquidity sweep AND an
   active (non-mitigated) inversion FVG are present on the 15m chart.
   Otherwise set signal to NONE and skip steps 7-9.
7. For entry timing confirmation, chart_set_timeframe to "5m", then
   data_get_ohlcv, and look for a confirmation trigger in the trade
   direction (market structure shift, momentum candle, smaller liquidity
   grab) near the inversion FVG. If unclear on 5m, repeat on "1m". Record
   which timeframe gave confirmation, or note none was found.
8. Only finalize signal as BUY or SELL if a lower-timeframe (5m or 1m) entry
   confirmation was found in step 7; otherwise set signal to NONE and
   explain the setup is still forming.
9. If signaling BUY or SELL, determine a realistic target price (the next
   significant liquidity/key level in the trade direction) and call
   draw_shape with type "line", color blue, and that price.

Respond with ONLY a single-line JSON object, no other text, no markdown
fences, with these exact fields: {"signal": "BUY", "symbol": "...",
"key_level_4h": 0000.0, "liquidity_magnet": 0000.0, "swept": true,
"sweep_price": 0000.0, "inversion_fvg": true, "ifvg_zone": "0000.0-0000.0",
"ifvg_status": "active", "entry_confirmed": true, "entry_timeframe": "5m",
"target_price": 0000.0, "reason": "..."} -- use the same fields for SELL,
and for NONE set the unmet fields to false/null and explain why in reason.
PROMPT_EOF
)

TOOL_PREFIX="mcp__${MCP_SERVER_NAME}__"
RAW_OUTPUT=$("$CLAUDE_BIN" -p \
  --allowedTools "${TOOL_PREFIX}chart_set_symbol" "${TOOL_PREFIX}chart_set_timeframe" "${TOOL_PREFIX}data_get_ohlcv" "${TOOL_PREFIX}quote_get" "${TOOL_PREFIX}draw_shape" "${TOOL_PREFIX}chart_get_state" \
  --output-format json \
  --max-turns 40 \
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
        str(inner.get("sweep_price") if inner.get("sweep_price") is not None else ""),
        str(inner.get("ifvg_zone") if inner.get("ifvg_zone") is not None else ""),
        str(inner.get("ifvg_status") or ""),
        str(inner.get("entry_confirmed") if inner.get("entry_confirmed") is not None else ""),
        str(inner.get("entry_timeframe") or ""),
        str(inner.get("target_price") if inner.get("target_price") is not None else ""),
        str(inner.get("reason") or ""),
    ]
    print("|".join(fields))
except Exception:
    print("|".join(["NONE","","","","","","","","parse-error"]))
')

IFS='|' read -r SIGNAL SYMBOL_OUT SWEEP_PRICE IFVG_ZONE IFVG_STATUS ENTRY_CONFIRMED ENTRY_TF TARGET_PRICE REASON <<< "$PARSED"

echo "$(timestamp) signal=$SIGNAL symbol=$SYMBOL_OUT sweep=$SWEEP_PRICE ifvg=$IFVG_ZONE status=$IFVG_STATUS entry_confirmed=$ENTRY_CONFIRMED entry_tf=$ENTRY_TF target=$TARGET_PRICE reason=$REASON" >> "$LOG_FILE"

if [ "$SIGNAL" = "BUY" ] || [ "$SIGNAL" = "SELL" ]; then
  MESSAGE=$(printf "Sweep: %s\nIFVG zone: %s (%s)\nEntry confirmed on: %s\nTarget: %s\n\n%s" "$SWEEP_PRICE" "$IFVG_ZONE" "$IFVG_STATUS" "$ENTRY_TF" "$TARGET_PRICE" "$REASON")
  curl -s -H "Title: TradingView Signal: $SIGNAL $SYMBOL_OUT" -H "Priority: high" -H "Tags: warning" --data-binary "$MESSAGE" "https://ntfy.sh/$NTFY_TOPIC" > /dev/null
fi
