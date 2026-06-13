"""Exchange abstraction for the pattern bot.

A thin `Broker` interface so the strategy/loop never touch exchange specifics —
to switch venues you swap the implementation, nothing else. Hyperliquid perps
are implemented now; Kraken Futures is a stub for the planned later switch.

All implementations honor `dry_run`: reads hit the real exchange (so the sim is
honest) when creds are present, but orders are only logged, never sent. The HL
order plumbing (rounding, accepted-vs-rejected interpretation, master/vault
routing) is lifted from funding-carry/bot/exchanges.py, generalized from
short-only to LONGS AND SHORTS.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("pattern-bot.broker")


class OrderError(RuntimeError):
    """An order/action was rejected by the exchange. Raised so a rejection is
    never mistaken for a fill (which would leave us thinking we hold a position
    we don't)."""


@dataclass
class BrokerPosition:
    coin: str
    side: str            # "long" | "short"
    size: float          # coin units, always positive
    entry_px: float
    mark_px: float
    unrealized_pnl: float = 0.0

    @property
    def notional(self) -> float:
        return self.size * self.mark_px


class Broker(ABC):
    """Minimum surface the loop + strategy need from a venue."""
    dry_run: bool = True

    @abstractmethod
    def candles(self, coin: str, interval: str, lookback: int) -> list[dict]:
        """Most recent `lookback` CLOSED candles, oldest→newest, as dicts with
        keys time, open, high, low, close (floats; time = open time in ms)."""

    @abstractmethod
    def mark_px(self, coin: str) -> float: ...

    @abstractmethod
    def positions(self) -> dict[str, BrokerPosition]: ...

    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def set_leverage(self, coin: str, lev: int) -> None: ...

    @abstractmethod
    def open_market(self, coin: str, side: str, size: float) -> dict:
        """Open `size` coin units long/short (IOC taker)."""

    @abstractmethod
    def close(self, coin: str, pos: BrokerPosition) -> dict:
        """Flatten an existing position (reduce-only IOC taker)."""


# --------------------------------------------------------------------------- #
# Hyperliquid
# --------------------------------------------------------------------------- #
class HyperliquidBroker(Broker):
    def __init__(self, base_url: str, account_address: str, secret_key: str,
                 vault_address: str = "", dry_run: bool = True,
                 slippage_bps: float = 5.0):
        self.dry_run = dry_run
        self.slippage = slippage_bps / 1e4
        # account_address = MASTER (approved the API wallet, where signing roots).
        # vault_address = optional sub-account to ACT ON; reads/orders target it.
        self.master_address = account_address
        self.vault_address = (vault_address or "").strip() or None
        self.address = self.vault_address or account_address
        from hyperliquid.info import Info
        self._info = Info(base_url, skip_ws=True)
        self._exch = None
        if secret_key and account_address:
            from hyperliquid.exchange import Exchange
            from eth_account import Account
            wallet = Account.from_key(secret_key)
            if self.vault_address:
                self._exch = Exchange(wallet, base_url, account_address=account_address,
                                      vault_address=self.vault_address)
            else:
                self._exch = Exchange(wallet, base_url, account_address=account_address)
        elif not dry_run:
            raise ValueError("Hyperliquid: secret_key/account_address required when dry_run=false")
        meta = self._info.meta()
        self._sz_dec = {a["name"]: int(a["szDecimals"]) for a in meta["universe"]}

    # ---- market data ----
    def candles(self, coin: str, interval: str, lookback: int) -> list[dict]:
        import time
        ms = _INTERVAL_MS.get(interval, 3_600_000)
        # pull a little extra so we have >= lookback CLOSED bars after dropping the
        # still-forming last candle.
        end = int(time.time() * 1000)
        start = end - (lookback + 2) * ms
        raw = self._info.post("/info", {"type": "candleSnapshot",
                                        "req": {"coin": coin, "interval": interval,
                                                "startTime": start, "endTime": end}}) or []
        out = [{"time": int(c["t"]), "open": float(c["o"]), "high": float(c["h"]),
                "low": float(c["l"]), "close": float(c["c"]), "vol": float(c.get("v", 0.0))}
               for c in raw]
        out.sort(key=lambda c: c["time"])
        # Drop the last candle if it's still forming (open time within one interval
        # of now) — we only ever act on closed bars.
        if out and out[-1]["time"] + ms > end:
            out = out[:-1]
        return out[-lookback:]

    def mark_px(self, coin: str) -> float:
        mids = self._info.all_mids()
        return float(mids.get(coin, 0.0))

    def positions(self) -> dict[str, BrokerPosition]:
        if not self.address:
            return {}
        st = self._info.user_state(self.address)
        out: dict[str, BrokerPosition] = {}
        for ap in st.get("assetPositions", []):
            p = ap.get("position", {})
            coin = p.get("coin")
            szi = float(p.get("szi", 0.0))
            if not coin or szi == 0.0:
                continue
            mark = float(p.get("positionValue") or 0.0) / abs(szi) if szi else 0.0
            out[coin] = BrokerPosition(
                coin=coin, side="long" if szi > 0 else "short", size=abs(szi),
                entry_px=float(p.get("entryPx") or 0.0), mark_px=mark,
                unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
            )
        return out

    def equity(self) -> float:
        if not self.address:
            return 0.0
        st = self._info.user_state(self.address)
        return float(st.get("marginSummary", {}).get("accountValue", 0.0))

    # ---- order plumbing (lifted from funding-carry exchanges.py) ----
    def _round_sz(self, coin: str, sz: float) -> float:
        return round(sz, self._sz_dec.get(coin, 4))

    def _round_px(self, coin: str, px: float) -> float:
        if px <= 0:
            return px
        max_dec = 6 - self._sz_dec.get(coin, 4)   # perps: MAX_DECIMALS(6) − szDecimals
        return round(float(f"{px:.5g}"), max_dec)  # ≤5 sig figs AND ≤max_dec places

    @staticmethod
    def _interpret(resp) -> tuple[bool, str]:
        if not isinstance(resp, dict):
            return False, f"non-dict response: {resp!r}"
        if resp.get("status") != "ok":
            return False, f"status={resp.get('status')!r} {resp.get('response')!r}"
        try:
            statuses = resp["response"]["data"]["statuses"]
        except (KeyError, TypeError):
            return True, "ok (non-order action)"
        msgs: list[str] = []
        accepted = False
        for s in statuses:
            if not isinstance(s, dict):
                continue
            if "error" in s:
                msgs.append(f"error: {s['error']}")
            elif "filled" in s:
                f = s["filled"]; accepted = True
                msgs.append(f"filled sz={f.get('totalSz')} @ {f.get('avgPx')}")
            elif "resting" in s:
                accepted = True
                msgs.append(f"resting oid={s['resting'].get('oid')}")
            else:
                msgs.append(str(s))
        return accepted, "; ".join(msgs) or "empty statuses"

    def _send(self, desc: str, fn):
        if self.dry_run:
            log.info("[DRY-RUN] HL would: %s", desc)
            return {"dry_run": True, "desc": desc}
        log.info("HL: %s", desc)
        resp = fn()
        accepted, detail = self._interpret(resp)
        if accepted:
            log.info("HL OK: %s — %s", desc, detail)
            return resp
        log.error("HL REJECTED: %s — %s", desc, detail)
        raise OrderError(f"{desc}: {detail}")

    def set_leverage(self, coin: str, lev: int) -> None:
        self._send(f"SET LEVERAGE {coin} = {lev}x (isolated)",
                   lambda: self._exch.update_leverage(lev, coin, is_cross=False))

    def open_market(self, coin: str, side: str, size: float) -> dict:
        is_buy = side == "long"
        mark = self.mark_px(coin)
        if mark <= 0:
            raise OrderError(f"no mark price for {coin}")
        # IOC limit with slippage tolerance: a buy pays up, a sell accepts lower.
        limit = mark * (1 + self.slippage) if is_buy else mark * (1 - self.slippage)
        sz = self._round_sz(coin, size)
        limit = self._round_px(coin, limit)
        return self._send(
            f"OPEN {side.upper()} {coin} sz={sz} @ {limit} (Ioc)",
            lambda: self._exch.order(coin, is_buy, sz, limit, {"limit": {"tif": "Ioc"}}, reduce_only=False),
        )

    def close(self, coin: str, pos: BrokerPosition) -> dict:
        is_buy = pos.side == "short"   # buy to close a short, sell to close a long
        mark = self.mark_px(coin)
        limit = mark * (1 + self.slippage) if is_buy else mark * (1 - self.slippage)
        sz = self._round_sz(coin, pos.size)
        limit = self._round_px(coin, limit)
        return self._send(
            f"CLOSE {pos.side.upper()} {coin} sz={sz} @ {limit} (Ioc) reduce_only",
            lambda: self._exch.order(coin, is_buy, sz, limit, {"limit": {"tif": "Ioc"}}, reduce_only=True),
        )


_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}


# --------------------------------------------------------------------------- #
# Kraken Futures (perps) — STUB for the planned later switch.
# --------------------------------------------------------------------------- #
class KrakenFuturesBroker(Broker):
    """TODO: implement against Kraken Futures (perps) via ccxt 'krakenfutures'.

    The interface is symmetric with HyperliquidBroker (longs + shorts, leverage),
    so finishing this is a contained follow-up:
      - ccxt.krakenfutures({apiKey, secret}); load_markets()
      - candles  -> fetch_ohlcv(symbol, timeframe, limit)
      - mark_px  -> fetch_ticker(symbol)['last'/'mark']
      - positions-> fetch_positions(); map to BrokerPosition
      - equity   -> fetch_balance() futures wallet
      - open/close -> create_order(symbol, 'market', side, amount, params={'reduceOnly':...})
      - set_leverage -> set_leverage(lev, symbol)
    Symbols on Kraken Futures look like 'PF_XBTUSD' / ccxt-unified 'BTC/USD:USD'.
    """

    def __init__(self, api_key: str, api_secret: str, dry_run: bool = True):
        self.dry_run = dry_run
        raise NotImplementedError(
            "KrakenFuturesBroker is a stub. Implement it via ccxt 'krakenfutures' "
            "when switching venues, then set exchange: kraken_futures in config.")

    def candles(self, coin, interval, lookback): raise NotImplementedError
    def mark_px(self, coin): raise NotImplementedError
    def positions(self): raise NotImplementedError
    def equity(self): raise NotImplementedError
    def set_leverage(self, coin, lev): raise NotImplementedError
    def open_market(self, coin, side, size): raise NotImplementedError
    def close(self, coin, pos): raise NotImplementedError


def make_broker(cfg: dict) -> Broker:
    """Instantiate the broker named by cfg['exchange']."""
    exch = str(cfg.get("exchange", "hyperliquid")).lower()
    dry = bool(cfg.get("dry_run", True))
    if exch == "hyperliquid":
        hl = cfg.get("hyperliquid", {}) or {}
        return HyperliquidBroker(
            base_url=hl.get("base_url", "https://api.hyperliquid.xyz"),
            account_address=hl.get("account_address", ""),
            secret_key=hl.get("secret_key", ""),
            vault_address=hl.get("vault_address", ""),
            dry_run=dry,
            slippage_bps=float(cfg.get("risk", {}).get("slippage_bps", 5.0)),
        )
    if exch == "kraken_futures":
        kf = cfg.get("kraken_futures", {}) or {}
        return KrakenFuturesBroker(kf.get("api_key", ""), kf.get("api_secret", ""), dry_run=dry)
    raise ValueError(f"unknown exchange {exch!r} (expected 'hyperliquid' or 'kraken_futures')")
