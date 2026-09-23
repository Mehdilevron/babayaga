"""Minimal Telegram Bot API sender plus per-token alert cooldown."""

from __future__ import annotations

import html
import logging
import time
from typing import Dict, Optional

import requests

from babayaga.memescan.scoring import ScoredPair

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout_s: float = 10.0):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.timeout_s = timeout_s

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                self.url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            logger.warning("telegram send failed: %s", exc)
            return False
        if not resp.ok:
            logger.warning("telegram send failed: HTTP %s %s", resp.status_code, resp.text[:200])
        return resp.ok


class AlertCooldown:
    """Suppresses re-alerting the same token within `cooldown_s` seconds."""

    def __init__(self, cooldown_s: float, clock=time.monotonic):
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._last: Dict[str, float] = {}

    def should_alert(self, key: str) -> bool:
        now = self.clock()
        last: Optional[float] = self._last.get(key)
        if last is not None and now - last < self.cooldown_s:
            return False
        self._last[key] = now
        return True


def format_alert(s: ScoredPair) -> str:
    p = s.pair
    reasons = "; ".join(s.reasons) or "passes all filters"
    return (
        f"<b>{html.escape(p.symbol)}</b> on {p.chain} · score {s.score:.0f}/100\n"
        f"price ${p.price_usd:.8g} · liq ${p.liquidity_usd:,.0f} · FDV ${p.fdv:,.0f}\n"
        f"h1 vol ${p.volume_h1:,.0f} · buys {p.buy_ratio_h1:.0%} · "
        f"5m {p.change_m5:+.1f}% · 1h {p.change_h1:+.1f}% · age {p.age_minutes / 60:.1f}h\n"
        f"{html.escape(reasons)}\n"
        f"{p.pair_url}\n"
        f"<i>Watchlist signal only, not a buy call. Check contract/holders before trading.</i>"
    )
