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


class HLOrderError(RuntimeError):
    """A Hyperliquid order/action was rejected (margin, agent not approved for
    the vault, IOC no-match, …). Raised so callers never treat a swallowed
    rejection as a fill and leg into a one-sided position."""


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
                 vault_address: str = "", dry_run: bool = True):
        self.dry_run = dry_run
        # account_address = MASTER (the account that approved the API wallet —
        # all signing is rooted here). vault_address = optional sub-account /
        # vault to ACT ON. HL routes an order to the sub only when the signed
        # action carries vaultAddress; account_address alone never does this.
        self.master_address = account_address
        self.vault_address = (vault_address or "").strip() or None
        # The address we read positions / margin for: the sub-account when we
        # operate on one, else the master.
        self.address = self.vault_address or account_address
        from hyperliquid.info import Info
        self._info = Info(base_url, skip_ws=True)
        self._exch = None
        if secret_key and account_address:
            from hyperliquid.exchange import Exchange
            from eth_account import Account
            wallet = Account.from_key(secret_key)
            if self.vault_address:
                # Master's API wallet signs; HL executes on the sub because
                # vault_address is included in the signed action payload.
                self._exch = Exchange(wallet, base_url,
                                      account_address=account_address,
                                      vault_address=self.vault_address)
            else:
                self._exch = Exchange(wallet, base_url,
                                      account_address=account_address)
        elif not dry_run:
            raise ValueError("Hyperliquid: secret_key/account_address required when dry_run=false")
        # cache sz decimals
        meta = self._info.meta()
        self._sz_dec = {a["name"]: int(a["szDecimals"]) for a in meta["universe"]}

    def _round_sz(self, coin: str, sz: float) -> float:
        d = self._sz_dec.get(coin, 4)
        return round(sz, d)

    def round_size(self, coin: str, sz: float) -> float:
        """Public: round a coin size to HL's lot for this coin. Used to size the hedge leg to
        the SAME rounded quantity the perp short will use, so the two legs stay delta-matched."""
        return self._round_sz(coin, sz)

    def _round_px(self, coin: str, px: float) -> float:
        """Hyperliquid rejects prices that aren't on a valid tick. The rule:
        ≤5 significant figures AND ≤ (6 − szDecimals) decimal places for perps
        (integer prices are exempt from the sig-fig cap). Passing a raw float
        like 9.453603849999999 yields 'Order has invalid price'."""
        if px <= 0:
            return px
        sz_dec = self._sz_dec.get(coin, 4)
        max_dec = 6 - sz_dec  # perps: MAX_DECIMALS(6) − szDecimals
        # :.5g caps to 5 significant figures (and renders large prices like
        # 105000.5 as 1.05e+05 → 105000.0, i.e. an integer, which HL exempts
        # from the sig-fig rule); the round() then enforces the decimal cap.
        return round(float(f"{px:.5g}"), max_dec)

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
    @staticmethod
    def _interpret(resp) -> tuple[bool, str]:
        """(accepted, detail) from a Hyperliquid SDK response.

        accepted is True only when HL took the order (filled or resting).
        A per-order rejection lands in statuses[].error (e.g. insufficient
        margin, agent not approved for the vault, IOC no-match); a top-level
        failure is status != "ok". Non-order actions (set_leverage) have no
        statuses array and are treated as accepted.
        """
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
                f = s["filled"]
                accepted = True
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
        raise HLOrderError(f"{desc}: {detail}")

    def open_short(self, coin: str, notional_usd: float, mark_px: float,
                   limit_px: float, tif: str = "Alo") -> dict:
        sz = self._round_sz(coin, notional_usd / mark_px)
        limit_px = self._round_px(coin, limit_px)
        return self._send(
            f"OPEN SHORT {coin} sz={sz} @ {limit_px} ({tif})",
            lambda: self._exch.order(coin, False, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=False),
        )

    def reduce_short(self, coin: str, reduce_notional_usd: float, mark_px: float,
                     limit_px: float, tif: str = "Ioc") -> dict:
        sz = self._round_sz(coin, reduce_notional_usd / mark_px)
        limit_px = self._round_px(coin, limit_px)
        # reduce a short = buy
        return self._send(
            f"REDUCE SHORT {coin} buy sz={sz} @ {limit_px} ({tif}) reduce_only",
            lambda: self._exch.order(coin, True, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=True),
        )

    def close_short(self, coin: str, pos: PerpPosition, limit_px: float, tif: str = "Ioc") -> dict:
        sz = self._round_sz(coin, abs(pos.size))
        limit_px = self._round_px(coin, limit_px)
        return self._send(
            f"CLOSE SHORT {coin} buy sz={sz} @ {limit_px} ({tif}) reduce_only",
            lambda: self._exch.order(coin, True, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=True),
        )

    def set_leverage(self, coin: str, lev: int) -> dict:
        return self._send(f"SET LEVERAGE {coin} = {lev}x (isolated)",
                          lambda: self._exch.update_leverage(lev, coin, is_cross=False))


class KrakenSpot:
    def __init__(self, api_key: str, api_secret: str, quote: str = "USD",
                 dry_run: bool = True, earn_enabled: bool = False,
                 earn_flex_only: bool = True, earn_min_wallet_frac: float = 0.05):
        self.dry_run = dry_run
        self.quote = quote
        import ccxt
        self._ex = ccxt.kraken({"apiKey": api_key or None, "secret": api_secret or None,
                                "enableRateLimit": True})
        self._have_keys = bool(api_key and api_secret)
        if not self._have_keys and not dry_run:
            raise ValueError("Kraken: api_key/api_secret required when dry_run=false")
        self._ex.load_markets()
        # --- Kraken Earn (yield on the otherwise-idle long-spot hedge) ---
        # FLEX (instant-unstake) strategies only by default, so the hedge stays
        # exit-able; bonded products lock for days and would strand a leg we may
        # need to sell to rebalance/close. All earn calls degrade gracefully:
        # a failure logs and is skipped, never breaking the carry loop.
        self.earn_enabled = earn_enabled
        self.earn_flex_only = earn_flex_only
        self.earn_min_wallet_frac = max(0.0, min(0.5, earn_min_wallet_frac))
        self._earn_strats: dict[str, dict] = {}   # coin -> {id, apr, lock, min}
        self._earn_strats_ts = 0.0
        self._earn_alloc: dict[str, float] = {}    # coin -> allocated amount (coin units)
        self._earn_alloc_ts = 0.0

    def symbol(self, coin: str) -> str:
        return f"{coin}/{self.quote}"

    def price(self, coin: str) -> float:
        return float(self._ex.fetch_ticker(self.symbol(coin))["last"])

    def bbo(self, coin: str) -> tuple[float, float]:
        """(best_bid, best_ask) for the spot pair. Falls back to last if a side is missing,
        so the basis gate and the marketable-limit hedge have a real price to work from.
        (Named ``bbo`` — ``quote`` is taken by the quote-currency attribute.)"""
        t = self._ex.fetch_ticker(self.symbol(coin))
        last = float(t.get("last") or 0.0)
        bid = float(t.get("bid") or last)
        ask = float(t.get("ask") or last)
        return bid, ask

    def wallet_balance(self, coin: str) -> float:
        """Free spot-wallet holding (immediately sellable). Excludes anything
        parked in Kraken Earn — that shows up under separate .S/.M/.F asset codes
        and must be deallocated before it can be sold."""
        if not self._have_keys:
            return 0.0
        b = self._ex.fetch_balance()
        return float(b.get("total", {}).get(coin, 0.0) or 0.0)

    def balance(self, coin: str) -> float:
        """Total economic holding of the hedge = the spot wallet PLUS every
        staked / earn variant Kraken reports under a separate asset code
        (BTC.M, BTC.S, BTC.F, …). Summing the asset codes captures Kraken
        Auto-Earn / staking and our own flex allocations in one shot, WITHOUT the
        double-count you'd get from wallet+Allocations — flex allocations already
        sit inside total[coin], while bonded ones appear only as the .M/.S code.

        Why this matters: a 2026-06-24 incident flattened a LINK leg because the
        old `wallet + earn_allocated` read the hedge as ~0 once auto-earn moved
        the spot into a separate code, triggering a buy-loop → kill switch."""
        if not self._have_keys:
            return 0.0
        tot = self._ex.fetch_balance().get("total", {}) or {}
        prefix = coin + "."
        total = 0.0
        for code, amt in tot.items():
            if code == coin or code.startswith(prefix):
                try:
                    total += float(amt or 0.0)
                except (TypeError, ValueError):
                    pass
        return total

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
        # Single chokepoint for every spot sale (rebalance / deleverage / close /
        # kill-switch): make sure enough is in the free wallet first, deallocating
        # from Kraken Earn just-in-time if the hedge is parked there.
        self._ensure_wallet(coin, amount_coin)
        sym = self.symbol(coin)
        if limit_px is not None:
            return self._send(f"SELL {amount_coin} {coin} limit @ {limit_px}",
                              lambda: self._ex.create_order(sym, "limit", "sell", amount_coin, limit_px))
        return self._send(f"SELL {amount_coin} {coin} market",
                          lambda: self._ex.create_order(sym, "market", "sell", amount_coin))

    # ------------------------------------------------------------------ #
    #  Kraken Earn — yield on the idle long-spot hedge (FLEX/instant only)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fmt(amount: float) -> str:
        # Kraken Earn wants the amount as a decimal string, not scientific notation.
        return f"{amount:.8f}".rstrip("0").rstrip(".") or "0"

    def _coin_of(self, kraken_asset: str) -> str:
        """Map a Kraken asset code (e.g. 'XBT', 'DOT', 'ETH') back to our unified
        coin symbol so Earn rows line up with the coins we trade."""
        try:
            return self._ex.safe_currency_code(kraken_asset)
        except Exception:  # noqa: BLE001
            return kraken_asset

    def _refresh_strategies(self) -> None:
        if not (self.earn_enabled and self._have_keys):
            return
        if self._earn_strats_ts and (time.time() - self._earn_strats_ts) < 3600:
            return
        try:
            resp = self._ex.privatePostEarnStrategies({"limit": 1000})
        except Exception as e:  # noqa: BLE001
            self._earn_strats_ts = time.time()  # back off before retrying
            log.warning("Earn/Strategies fetch failed: %s", e)
            return
        items = ((resp or {}).get("result") or {}).get("items", []) or []
        best: dict[str, dict] = {}
        for it in items:
            asset = it.get("asset")
            if not asset:
                continue
            lock = ((it.get("lock_type") or {}).get("type") or "").lower()
            if self.earn_flex_only and lock != "instant":
                continue
            if not it.get("can_allocate", True):
                continue
            apr_est = it.get("apr_estimate") or {}
            try:
                lo = float(apr_est.get("low", 0) or 0)
                hi = float(apr_est.get("high", lo) or lo)
                apr = (lo + hi) / 2.0 / 100.0   # Kraken returns APR as a percent string
            except (TypeError, ValueError):
                apr = 0.0
            coin = self._coin_of(asset)
            cur = best.get(coin)
            if cur is None or apr > cur["apr"]:
                try:
                    mn = float(it.get("user_min_allocation", 0) or 0)
                except (TypeError, ValueError):
                    mn = 0.0
                best[coin] = {"id": it.get("id"), "apr": apr, "lock": lock, "min": mn}
        self._earn_strats = best
        self._earn_strats_ts = time.time()

    def flex_apy(self, coin: str) -> float:
        """Best instant-unstake Earn APY for `coin` as a fraction (0.105 = 10.5%),
        or 0.0 if earn is disabled / no flex strategy exists for this coin."""
        if not (self.earn_enabled and self._have_keys):
            return 0.0
        self._refresh_strategies()
        s = self._earn_strats.get(coin)
        return float(s["apr"]) if s else 0.0

    def _refresh_allocations(self) -> None:
        if not (self.earn_enabled and self._have_keys):
            return
        # Back off on the timestamp (not on dict-truthiness) so an empty result
        # set or a transient error can't spam the endpoint every loop call.
        if self._earn_alloc_ts and (time.time() - self._earn_alloc_ts) < 30:
            return
        try:
            # No args: Kraken rejects a Python bool for hide_zero_allocations
            # ("EGeneral:Invalid arguments"); the default (all allocations) is fine
            # since we filter by amount below.
            resp = self._ex.privatePostEarnAllocations({})
        except Exception as e:  # noqa: BLE001
            self._earn_alloc_ts = time.time()  # back off 30s before retrying
            log.warning("Earn/Allocations fetch failed: %s", e)
            return
        items = ((resp or {}).get("result") or {}).get("items", []) or []
        out: dict[str, float] = {}
        for it in items:
            asset = it.get("native_asset") or it.get("asset")
            if not asset:
                continue
            tot = (it.get("amount_allocated") or {}).get("total") or {}
            try:
                amt = float(tot.get("native", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            coin = self._coin_of(asset)
            out[coin] = out.get(coin, 0.0) + amt
        self._earn_alloc = out
        self._earn_alloc_ts = time.time()

    def earn_allocated(self, coin: str) -> float:
        """Amount of `coin` currently parked in Kraken Earn (coin units)."""
        if not (self.earn_enabled and self._have_keys):
            return 0.0
        self._refresh_allocations()
        return float(self._earn_alloc.get(coin, 0.0))

    def allocate(self, coin: str, amount: float) -> Optional[dict]:
        if not (self.earn_enabled and self._have_keys) or amount <= 0:
            return None
        self._refresh_strategies()
        s = self._earn_strats.get(coin)
        if not s or not s.get("id"):
            return None
        if amount < max(s.get("min", 0.0), 1e-9):
            return None
        self._earn_alloc_ts = 0.0  # invalidate cache; next read re-fetches
        return self._send(
            f"EARN ALLOCATE {self._fmt(amount)} {coin} -> {s['id']} (flex ~{s['apr']:.1%})",
            lambda: self._ex.privatePostEarnAllocate({"amount": self._fmt(amount), "strategy_id": s["id"]}),
        )

    def deallocate(self, coin: str, amount: float) -> Optional[dict]:
        if not (self.earn_enabled and self._have_keys) or amount <= 0:
            return None
        s = self._earn_strats.get(coin)
        if not s or not s.get("id"):
            return None
        self._earn_alloc_ts = 0.0
        return self._send(
            f"EARN DEALLOCATE {self._fmt(amount)} {coin} <- {s['id']}",
            lambda: self._ex.privatePostEarnDeallocate({"amount": self._fmt(amount), "strategy_id": s["id"]}),
        )

    def _earn_allocations_for(self, coin: str) -> list[tuple[str, float]]:
        """[(strategy_id, native_amount)] currently staked/allocated for `coin`,
        from Earn/Allocations. Used to unwind funds (incl. Kraken Auto-Earn) before
        a sell — independent of our own earn_enabled flag."""
        out: list[tuple[str, float]] = []
        if not self._have_keys:
            return out
        try:
            resp = self._ex.privatePostEarnAllocations({})
        except Exception as e:  # noqa: BLE001
            log.warning("Earn/Allocations (unstake) failed: %s", e)
            return out
        for it in ((resp or {}).get("result") or {}).get("items", []) or []:
            if self._coin_of(it.get("native_asset") or it.get("asset") or "") != coin:
                continue
            sid = it.get("strategy_id")
            try:
                amt = float(((it.get("amount_allocated") or {}).get("total") or {}).get("native", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if sid and amt > 0:
                out.append((sid, amt))
        return out

    def unstake_all(self, coin: str) -> int:
        """Deallocate EVERY earn/staking allocation for `coin` back to the wallet
        (flex returns instantly; bonded begins unbonding). Returns the count of
        deallocations issued. Skipped in dry_run via _send."""
        n = 0
        for sid, amt in self._earn_allocations_for(coin):
            self._send(
                f"EARN DEALLOCATE {self._fmt(amt)} {coin} <- {sid}",
                lambda sid=sid, amt=amt: self._ex.privatePostEarnDeallocate(
                    {"amount": self._fmt(amt), "strategy_id": sid}),
            )
            n += 1
        self._earn_alloc_ts = 0.0
        return n

    def _ensure_wallet(self, coin: str, amount: float) -> None:
        """Before selling `amount` of `coin`, pull any shortfall out of Earn/staking
        and wait (bounded) for the funds to land in the wallet. Runs whenever we
        hold keys (NOT gated on earn_enabled — pre-existing Kraken Auto-Earn must be
        unwound too). No-op in dry_run (orders aren't sent, so nothing to pull)."""
        if not self._have_keys or self.dry_run:
            return
        if self.wallet_balance(coin) >= amount:
            return
        if self.unstake_all(coin) == 0:
            return  # nothing staked to free
        # Flex returns funds quickly, but Deallocate is async — poll the wallet
        # until they land, up to ~30s. If they don't fully land (bonded/unbonding)
        # we proceed and sell what's free, rather than block forever.
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.wallet_balance(coin) >= amount * 0.999:
                return
            time.sleep(2)
        log.warning("EARN/STAKE: %s wallet still < %s after unstake+30s; "
                    "selling what's free (rest may be bonded/unbonding)",
                    coin, self._fmt(amount))
