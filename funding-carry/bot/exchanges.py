"""Exchange wrappers for the funding-carry bot.

- MarketData : public HL data (mid prices + current funding per coin). No auth.
- HyperliquidPerp : the short-perp leg. Read positions/margin; place/reduce/close
  shorts. Honors dry_run (logs intended orders, places none).
- KrakenSpot : the long-spot leg (held outright, no leverage). Read balances;
  buy/sell. Honors dry_run. Kraken Pro spot fees are covered by your KFEE credit.

In dry_run: if credentials are present we still READ real state (so the sim is
honest); if absent we mock reads (positions/balances = 0). Orders are never sent
in dry_run regardless.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("funding-carry.exch")


@dataclass
class PerpPosition:
    coin: str
    size: float          # signed; negative = short (units of the coin)
    entry_px: float
    mark_px: float
    margin_used: float   # USD margin allocated to this position
    unrealized_pnl: float
    liquidation_px: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.size) * self.mark_px

    @property
    def margin_frac(self) -> float:
        """Margin allocated as a fraction of current notional (lower = more levered / stressed)."""
        return self.margin_used / self.notional if self.notional > 0 else 0.0

    @property
    def liq_room_frac(self) -> float:
        """For a short: (liq_px - mark_px)/mark_px. Larger = safer. 1.0 if no liq price."""
        if self.liquidation_px <= 0 or self.mark_px <= 0:
            return 1.0
        return max(0.0, (self.liquidation_px - self.mark_px) / self.mark_px)


class MarketData:
    """Public Hyperliquid data: mid prices and current funding rates."""

    def __init__(self, base_url: str):
        from hyperliquid.info import Info
        self._info = Info(base_url, skip_ws=True)

    def mids(self) -> dict[str, float]:
        return {k: float(v) for k, v in self._info.all_mids().items()}

    def funding(self) -> dict[str, float]:
        """coin -> current hourly funding rate (signed; >0 => longs pay shorts)."""
        meta, ctxs = self._info.meta_and_asset_ctxs()
        out: dict[str, float] = {}
        for asset, ctx in zip(meta["universe"], ctxs):
            try:
                out[asset["name"]] = float(ctx.get("funding", 0.0))
            except (TypeError, ValueError):
                pass
        return out

    def funding_history(self, coin: str, start_ms: int) -> list[dict]:
        return self._info.funding_history(coin, start_ms)


class HyperliquidPerp:
    def __init__(self, base_url: str, account_address: str, secret_key: str,
                 dry_run: bool = True):
        self.dry_run = dry_run
        self.address = account_address
        from hyperliquid.info import Info
        self._info = Info(base_url, skip_ws=True)
        self._exch = None
        if secret_key and account_address:
            from hyperliquid.exchange import Exchange
            from eth_account import Account
            wallet = Account.from_key(secret_key)
            self._exch = Exchange(wallet, base_url, account_address=account_address)
        elif not dry_run:
            raise ValueError("Hyperliquid: secret_key/account_address required when dry_run=false")
        # cache sz decimals
        meta = self._info.meta()
        self._sz_dec = {a["name"]: int(a["szDecimals"]) for a in meta["universe"]}

    def _round_sz(self, coin: str, sz: float) -> float:
        d = self._sz_dec.get(coin, 4)
        return round(sz, d)

    def user_state(self) -> dict:
        if not self.address:
            return {"assetPositions": [], "marginSummary": {"accountValue": "0"}}
        return self._info.user_state(self.address)

    def positions(self) -> dict[str, PerpPosition]:
        st = self.user_state()
        out: dict[str, PerpPosition] = {}
        for ap in st.get("assetPositions", []):
            p = ap.get("position", {})
            coin = p.get("coin")
            szi = float(p.get("szi", 0.0))
            if not coin or szi == 0.0:
                continue
            out[coin] = PerpPosition(
                coin=coin, size=szi,
                entry_px=float(p.get("entryPx") or 0.0),
                mark_px=float((p.get("positionValue") or 0.0)) / abs(szi) if szi else 0.0,
                margin_used=float(p.get("marginUsed") or 0.0),
                unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
                liquidation_px=float(p.get("liquidationPx") or 0.0),
            )
        return out

    def account_value(self) -> float:
        return float(self.user_state().get("marginSummary", {}).get("accountValue", 0.0))

    # --- order placement (skipped in dry_run) ---
    def _send(self, desc: str, fn):
        if self.dry_run:
            log.info("[DRY-RUN] HL would: %s", desc)
            return {"dry_run": True, "desc": desc}
        log.info("HL: %s", desc)
        return fn()

    def open_short(self, coin: str, notional_usd: float, mark_px: float,
                   limit_px: float, tif: str = "Alo") -> dict:
        sz = self._round_sz(coin, notional_usd / mark_px)
        return self._send(
            f"OPEN SHORT {coin} sz={sz} @ {limit_px} ({tif})",
            lambda: self._exch.order(coin, False, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=False),
        )

    def reduce_short(self, coin: str, reduce_notional_usd: float, mark_px: float,
                     limit_px: float, tif: str = "Ioc") -> dict:
        sz = self._round_sz(coin, reduce_notional_usd / mark_px)
        # reduce a short = buy
        return self._send(
            f"REDUCE SHORT {coin} buy sz={sz} @ {limit_px} ({tif}) reduce_only",
            lambda: self._exch.order(coin, True, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=True),
        )

    def close_short(self, coin: str, pos: PerpPosition, limit_px: float, tif: str = "Ioc") -> dict:
        sz = self._round_sz(coin, abs(pos.size))
        return self._send(
            f"CLOSE SHORT {coin} buy sz={sz} @ {limit_px} ({tif}) reduce_only",
            lambda: self._exch.order(coin, True, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=True),
        )

    def set_leverage(self, coin: str, lev: int) -> dict:
        return self._send(f"SET LEVERAGE {coin} = {lev}x (isolated)",
                          lambda: self._exch.update_leverage(lev, coin, is_cross=False))


class KrakenSpot:
    def __init__(self, api_key: str, api_secret: str, quote: str = "USD",
                 dry_run: bool = True):
        self.dry_run = dry_run
        self.quote = quote
        import ccxt
        self._ex = ccxt.kraken({"apiKey": api_key or None, "secret": api_secret or None,
                                "enableRateLimit": True})
        self._have_keys = bool(api_key and api_secret)
        if not self._have_keys and not dry_run:
            raise ValueError("Kraken: api_key/api_secret required when dry_run=false")
        self._ex.load_markets()

    def symbol(self, coin: str) -> str:
        return f"{coin}/{self.quote}"

    def price(self, coin: str) -> float:
        return float(self._ex.fetch_ticker(self.symbol(coin))["last"])

    def balance(self, coin: str) -> float:
        if not self._have_keys:
            return 0.0
        b = self._ex.fetch_balance()
        return float(b.get("total", {}).get(coin, 0.0) or 0.0)

    def usd_balance(self) -> float:
        if not self._have_keys:
            return 0.0
        b = self._ex.fetch_balance()
        return float(b.get("total", {}).get(self.quote, 0.0) or 0.0)

    def _send(self, desc: str, fn):
        if self.dry_run:
            log.info("[DRY-RUN] Kraken would: %s", desc)
            return {"dry_run": True, "desc": desc}
        log.info("Kraken: %s", desc)
        return fn()

    def buy(self, coin: str, amount_coin: float, limit_px: Optional[float] = None) -> dict:
        sym = self.symbol(coin)
        if limit_px is not None:
            return self._send(f"BUY {amount_coin} {coin} limit @ {limit_px}",
                              lambda: self._ex.create_order(sym, "limit", "buy", amount_coin, limit_px))
        return self._send(f"BUY {amount_coin} {coin} market",
                          lambda: self._ex.create_order(sym, "market", "buy", amount_coin))

    def sell(self, coin: str, amount_coin: float, limit_px: Optional[float] = None) -> dict:
        sym = self.symbol(coin)
        if limit_px is not None:
            return self._send(f"SELL {amount_coin} {coin} limit @ {limit_px}",
                              lambda: self._ex.create_order(sym, "limit", "sell", amount_coin, limit_px))
        return self._send(f"SELL {amount_coin} {coin} market",
                          lambda: self._ex.create_order(sym, "market", "sell", amount_coin))
