"""Hyperliquid exchange tools — perps, spot, and vaults.

Env vars:
    HYPERLIQUID_ACCOUNT_ADDRESS    # MASTER 0x… address (the one that approved the agent)
    HYPERLIQUID_API_PRIVATE_KEY    # API wallet (agent) private key — approved on MASTER
    HYPERLIQUID_VAULT_ADDRESS      # OPTIONAL: sub-account / vault 0x… to act on.
                                   # If set, reads query this address and signed
                                   # actions include vaultAddress=<this> so HL
                                   # executes them on the sub. Master's agent
                                   # signs (no extra approval needed on the sub).
    HYPERLIQUID_TESTNET            # optional "true" to route to testnet

HLP (Hyperliquid LP vault) canonical address:
    0xdfc24b077bc1425ad1dea75bcb6f8158e10df303
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

HLP_VAULT_ADDRESS = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"


def _base_url() -> str:
    testnet = os.environ.get("HYPERLIQUID_TESTNET", "").lower() in ("1", "true", "yes")
    return (
        "https://api.hyperliquid-testnet.xyz"
        if testnet
        else "https://api.hyperliquid.xyz"
    )


def _credentials_present() -> bool:
    return bool(
        os.environ.get("HYPERLIQUID_ACCOUNT_ADDRESS")
        and os.environ.get("HYPERLIQUID_API_PRIVATE_KEY")
    )


def validate() -> dict[str, Any]:
    """Smoke-test Hyperliquid setup:
    1. Master address resolves (user_state returns marginSummary).
    2. Private key is a valid eth_account key.
    3. Derived agent is in MASTER's approved-agents list (https://app.hyperliquid.xyz/API).
    4. If HYPERLIQUID_VAULT_ADDRESS is set, verify it's a sub-account of the
       master (otherwise the master's agent can't act on it).

    Raises on any check failure.
    """
    from eth_account import Account
    master = _master_address()
    vault = _vault_address()
    info = _info()

    us = info.user_state(master)
    if not us or "marginSummary" not in us:
        raise RuntimeError(
            f"HL user_state for master {master} returned no marginSummary — address invalid?"
        )

    agent_addr = Account.from_key(
        os.environ["HYPERLIQUID_API_PRIVATE_KEY"]
    ).address.lower()
    try:
        agents = info.post("/info", {"type": "extraAgents", "user": master}) or []
    except Exception as e:  # noqa: BLE001
        agent_check: Any = f"skipped — extraAgents call failed: {e}"
    else:
        approved = {(a.get("address") or "").lower() for a in agents if isinstance(a, dict)}
        if agent_addr not in approved:
            raise RuntimeError(
                f"HL private key derives agent {agent_addr} which is NOT in the "
                f"approved-agents list for master {master}. Approve it at "
                "https://app.hyperliquid.xyz/API before placing signed orders."
            )
        agent_check = f"ok ({len(approved)} approved on master)"

    out: dict[str, Any] = {
        "master": master,
        "master_account_value": (us.get("marginSummary") or {}).get("accountValue"),
        "agent_address": agent_addr,
        "agent_check": agent_check,
    }

    if vault:
        try:
            subs = info.post("/info", {"type": "subAccounts", "user": master}) or []
        except Exception as e:  # noqa: BLE001
            out["vault_check"] = f"skipped — subAccounts call failed: {e}"
        else:
            sub_addrs = {(s.get("subAccountUser") or s.get("address") or "").lower()
                         for s in subs if isinstance(s, dict)}
            if vault.lower() not in sub_addrs:
                raise RuntimeError(
                    f"HYPERLIQUID_VAULT_ADDRESS {vault} is not a sub-account of "
                    f"master {master}. Master's agent can't act on it. Either "
                    "create the sub under this master, point VAULT_ADDRESS at a "
                    "real sub, or unset it to operate on master directly."
                )
            out["vault"] = vault
            vault_us = info.user_state(vault) or {}
            out["vault_account_value"] = (
                (vault_us.get("marginSummary") or {}).get("accountValue")
            )
            out["vault_check"] = f"ok (1 of {len(sub_addrs)} sub-accounts)"

    return out


def _master_address() -> str:
    """The MASTER address — the wallet that approved the API agent. All signing
    is rooted here."""
    return os.environ["HYPERLIQUID_ACCOUNT_ADDRESS"]


def _vault_address() -> str | None:
    """Optional sub-account / vault address to route actions to. None when
    operating directly on the master."""
    v = os.environ.get("HYPERLIQUID_VAULT_ADDRESS")
    return v.strip() if v and v.strip() else None


def _target_address() -> str:
    """The address whose state we want to read/trade. Equals vault if set,
    else the master."""
    return _vault_address() or _master_address()


# Back-compat: existing code paths called _account_address() to mean "the address
# we're operating on" — keep that semantics (target), not the master.
_account_address = _target_address


@lru_cache(maxsize=1)
def _info():
    from hyperliquid.info import Info
    return Info(_base_url(), skip_ws=True)


@lru_cache(maxsize=1)
def _exchange():
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    wallet = Account.from_key(os.environ["HYPERLIQUID_API_PRIVATE_KEY"])
    vault = _vault_address()
    if vault:
        # Master's agent signs; HL executes on the sub because vault_address
        # is included in the signed action payload.
        return Exchange(
            wallet,
            _base_url(),
            account_address=_master_address(),
            vault_address=vault,
        )
    return Exchange(wallet, _base_url(), account_address=_master_address())


@lru_cache(maxsize=1)
def _master_exchange():
    """Exchange scoped to the MASTER (no vaultAddress). Required for account-level
    actions — external withdrawals and sub-account transfers — which operate on the
    master, not a sub. (When no vault is configured this equals _exchange().)"""
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    wallet = Account.from_key(os.environ["HYPERLIQUID_API_PRIVATE_KEY"])
    return Exchange(wallet, _base_url(), account_address=_master_address())


def _annualize_funding(hourly: float) -> float:
    """Convert HL's hourly funding rate to an APR (× 24 × 365)."""
    return hourly * 24 * 365


def register(mcp: FastMCP) -> int:
    if not _credentials_present():
        return 0

    # ----- Public / market data -----------------------------------------

    @mcp.tool()
    def hyperliquid_get_meta() -> dict[str, Any]:
        """Hyperliquid perp universe: list of tradable coins, max leverage,
        size decimals, etc."""
        return _info().meta()

    @mcp.tool()
    def hyperliquid_get_spot_meta() -> dict[str, Any]:
        """Hyperliquid spot universe: tokens + trading pairs."""
        return _info().spot_meta()

    @mcp.tool()
    def hyperliquid_get_all_mids() -> dict[str, str]:
        """Latest mid prices for every Hyperliquid coin keyed by coin name."""
        return _info().all_mids()

    @mcp.tool()
    def hyperliquid_get_orderbook(coin: str, depth: int = 10) -> dict[str, Any]:
        """Hyperliquid perp order book: best bid/ask, spread (bps), top levels +
        USD depth. A short fills at the BID — use this (not all_mids/mark) for
        accurate carry entry pricing."""
        l2 = _info().l2_snapshot(coin.upper())
        lv = l2.get("levels") or [[], []]
        bids = [[float(x["px"]), float(x["sz"])] for x in (lv[0] or [])[:depth]]
        asks = [[float(x["px"]), float(x["sz"])] for x in (lv[1] or [])[:depth]]
        bb = bids[0][0] if bids else None
        ba = asks[0][0] if asks else None
        return {
            "coin": coin.upper(),
            "best_bid": bb,
            "best_ask": ba,
            "spread_bps": (ba - bb) / bb * 1e4 if bb and ba else None,
            "bid_depth_usd": sum(p * q for p, q in bids),
            "ask_depth_usd": sum(p * q for p, q in asks),
            "bids": bids,
            "asks": asks,
        }

    @mcp.tool()
    def hyperliquid_get_funding_rates() -> list[dict[str, Any]]:
        """Current funding rate (hourly + annualized) for every Hyperliquid perp.
        Positive => longs pay shorts. Sorted with most positive first.
        """
        meta, ctxs = _info().meta_and_asset_ctxs()
        out: list[dict[str, Any]] = []
        for asset, ctx in zip(meta.get("universe", []), ctxs):
            try:
                hourly = float(ctx.get("funding", 0.0))
            except (TypeError, ValueError):
                hourly = 0.0
            out.append({
                "coin": asset.get("name"),
                "hourly": hourly,
                "apr": _annualize_funding(hourly),
                "mark_px": ctx.get("markPx"),
                "open_interest": ctx.get("openInterest"),
                "day_ntl_vlm": ctx.get("dayNtlVlm"),
                "max_leverage": asset.get("maxLeverage"),
            })
        out.sort(key=lambda r: r["hourly"], reverse=True)
        return out

    @mcp.tool()
    def hyperliquid_get_funding_history(coin: str, hours: int = 24) -> list[dict]:
        """Historical hourly funding for a Hyperliquid perp.
        hours: lookback window in hours (default 24)."""
        start_ms = int(time.time() * 1000) - hours * 3600 * 1000
        return _info().funding_history(coin.upper(), start_ms)

    # ----- Account state -------------------------------------------------

    @mcp.tool()
    def hyperliquid_get_perp_account() -> dict[str, Any]:
        """Hyperliquid perp account: positions, margin summary, account value."""
        return _info().user_state(_account_address())

    @mcp.tool()
    def hyperliquid_get_accounts_overview() -> dict[str, Any]:
        """Perp account value + open positions for BOTH the master and the
        configured sub. The MCP TRADES the sub, but bridge deposits credit the
        MASTER — use this to see where collateral actually landed and whether a
        master→sub transfer is needed before opening."""
        info = _info()
        master = _master_address()
        target = _target_address()

        def _summ(addr: str) -> dict[str, Any]:
            us = info.user_state(addr) or {}
            ms = us.get("marginSummary") or {}
            return {
                "address": addr,
                "account_value": ms.get("accountValue"),
                "withdrawable": us.get("withdrawable"),
                "open_positions": [
                    {
                        "coin": (p.get("position") or {}).get("coin"),
                        "szi": (p.get("position") or {}).get("szi"),
                        "entryPx": (p.get("position") or {}).get("entryPx"),
                        "liquidationPx": (p.get("position") or {}).get("liquidationPx"),
                    }
                    for p in (us.get("assetPositions") or [])
                    if float((p.get("position") or {}).get("szi") or 0) != 0
                ],
            }

        out: dict[str, Any] = {
            "trading_account": "sub" if _vault_address() else "master",
            "master": _summ(master),
        }
        if target != master:
            out["sub"] = _summ(target)
        return out

    @mcp.tool()
    def hyperliquid_get_spot_balances() -> dict[str, Any]:
        """Hyperliquid spot balances per token."""
        return _info().spot_user_state(_account_address())

    @mcp.tool()
    def hyperliquid_get_open_orders() -> list[dict]:
        """All open Hyperliquid orders for the account."""
        return _info().open_orders(_account_address())

    @mcp.tool()
    def hyperliquid_get_fills(limit: int = 50) -> list[dict]:
        """Recent Hyperliquid fills for the account (most recent last)."""
        fills = _info().user_fills(_account_address()) or []
        return fills[-limit:]

    @mcp.tool()
    def hyperliquid_get_user_funding_payments(hours: int = 168) -> list[dict]:
        """Realized funding payments paid/earned by the account over the lookback
        window (default 168h = 1 week). Positive `usdc` means received."""
        start_ms = int(time.time() * 1000) - hours * 3600 * 1000
        # SDK exposes this as `user_funding_history` — falls back to raw POST if missing.
        info = _info()
        method = getattr(info, "user_funding_history", None)
        if method:
            return method(_account_address(), start_ms)
        # Manual POST fallback (older SDK).
        return info.post("/info", {
            "type": "userFunding",
            "user": _account_address(),
            "startTime": start_ms,
        })

    @mcp.tool()
    def hyperliquid_get_vault_equities() -> list[dict]:
        """Equity per vault the account is subscribed to (HLP, user vaults).
        Includes lockup / unlock-time info if the vault has a withdraw delay."""
        return _info().user_vault_equities(_account_address())

    @mcp.tool()
    def hyperliquid_get_hlp_summary() -> dict[str, Any]:
        """Convenience: HLP-specific subscription summary (equity + unlock time
        + estimated APR if recently published)."""
        equities = _info().user_vault_equities(_account_address()) or []
        mine = next(
            (
                v for v in equities
                if (v.get("vaultAddress") or "").lower() == HLP_VAULT_ADDRESS
            ),
            None,
        )
        details: dict[str, Any] = {}
        try:
            details = _info().query_vault_details(HLP_VAULT_ADDRESS) or {}
        except Exception as e:  # noqa: BLE001
            details = {"details_error": str(e)}
        return {
            "vault_address": HLP_VAULT_ADDRESS,
            "subscription": mine,
            "details": details,
        }

    # ----- Trading (perp) -----------------------------------------------

    @mcp.tool()
    def hyperliquid_place_perp_order(
        coin: str,
        side: str,
        size: float,
        order_type: str = "limit",
        price: float | None = None,
        reduce_only: bool = False,
        tif: str = "Gtc",
    ) -> dict[str, Any]:
        """Place a Hyperliquid perp order.

        side: BUY | SELL (case insensitive)
        order_type: "limit" | "market"
        price: required for limit; ignored for market (slippage handled internally)
        tif: Gtc | Ioc | Alo  (limit orders only)
        """
        is_buy = side.upper() == "BUY"
        coin_u = coin.upper()
        if order_type.lower() == "market":
            return _exchange().market_open(coin_u, is_buy, size, px=price)
        if price is None:
            raise ValueError("price is required for limit orders")
        return _exchange().order(
            coin_u,
            is_buy,
            size,
            price,
            {"limit": {"tif": tif}},
            reduce_only=reduce_only,
        )

    @mcp.tool()
    def hyperliquid_market_close_position(coin: str) -> dict[str, Any]:
        """Market-close the current Hyperliquid perp position for a coin."""
        return _exchange().market_close(coin.upper())

    @mcp.tool()
    def hyperliquid_cancel_perp_order(coin: str, order_id: int) -> dict[str, Any]:
        """Cancel a Hyperliquid perp order by oid."""
        return _exchange().cancel(coin.upper(), order_id)

    @mcp.tool()
    def hyperliquid_set_leverage(
        coin: str, leverage: int, cross: bool = True
    ) -> dict[str, Any]:
        """Set leverage for a Hyperliquid perp.
        cross=True for cross margin, False for isolated."""
        return _exchange().update_leverage(leverage, coin.upper(), is_cross=cross)

    # ----- Transfers / vault --------------------------------------------

    @mcp.tool()
    def hyperliquid_bridge_usdc(amount: float, to_perp: bool = True) -> dict[str, Any]:
        """Move USDC between Hyperliquid spot and perp wallets.
        to_perp=True: spot -> perp. to_perp=False: perp -> spot."""
        return _exchange().usd_class_transfer(amount, to_perp=to_perp)

    @mcp.tool()
    def hyperliquid_vault_transfer(
        usdc_amount: float,
        is_deposit: bool = True,
        vault_address: str = HLP_VAULT_ADDRESS,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Deposit to or withdraw from a Hyperliquid vault (HLP by default).

        Safety: ``confirm`` must be ``True`` to actually submit. Otherwise a
        dry-run is returned. HLP has a 4-day withdraw lock — verify before
        depositing.
        """
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually submit this vault transfer.",
                "vault_address": vault_address,
                "is_deposit": is_deposit,
                "usdc_amount": usdc_amount,
                "note": (
                    "HLP withdraws have a 4-day unlock period from the most "
                    "recent deposit."
                ),
            }
        return _exchange().vault_usd_transfer(
            vault_address, is_deposit, usdc_amount
        )

    @mcp.tool()
    def hyperliquid_withdraw_usdc(
        destination: str, amount: float, confirm: bool = False
    ) -> dict[str, Any]:
        """Withdraw USDC from Hyperliquid to an Arbitrum address (~$1 bridge fee,
        deducted from the amount). Withdraws from the configured account/sub —
        funds must already be on it (use hyperliquid_transfer_subaccount for a sub).

        Safety: ``confirm`` must be ``True`` to submit. Otherwise dry-run.
        """
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually submit this withdrawal.",
                "destination": destination,
                "amount": amount,
            }
        # Withdrawals are a MASTER-level action — funds must be on the master
        # (use hyperliquid_transfer_subaccount to pull from a sub first).
        return _master_exchange().withdraw_from_bridge(amount, destination)

    @mcp.tool()
    def hyperliquid_transfer_subaccount(
        usd_amount: float,
        to_master: bool = True,
        sub_address: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Move USDC between the master and a sub-account.

        to_master=True : sub -> master (do this before an external withdrawal).
        to_master=False: master -> sub.
        sub_address defaults to the configured HYPERLIQUID_VAULT_ADDRESS sub.

        Safety: confirm=True to submit; otherwise dry-run.
        """
        sub = sub_address or _vault_address()
        if not sub:
            return {"error": "no sub-account set (HYPERLIQUID_VAULT_ADDRESS) and none passed"}
        if not confirm:
            return {
                "dry_run": True,
                "warning": "Set confirm=True to actually submit this transfer.",
                "sub_account": sub,
                "direction": "sub->master" if to_master else "master->sub",
                "usd_amount": usd_amount,
            }
        # HL's subAccountTransfer `usd` is micro-USDC (6 decimals): $1 = 1_000_000.
        usd = int(round(usd_amount * 1_000_000))
        return _master_exchange().sub_account_transfer(sub, is_deposit=(not to_master), usd=usd)

    @mcp.tool()
    def hyperliquid_get_deposit_info() -> dict[str, Any]:
        """How to deposit USDC INTO Hyperliquid (for moving capital from another
        venue). HL is non-custodial: USDC (Arbitrum) is sent to the bridge, which
        credits the SENDING wallet's HL account. So you CANNOT deposit straight
        from a CEX (Kraken/WhiteBIT) — the exchange's hot wallet would be credited,
        not you. Route: withdraw from the CEX to YOUR OWN Arbitrum wallet, then send
        from that wallet to the bridge. HL -> CEX works directly via
        hyperliquid_withdraw_usdc."""
        return {
            "asset": "USDC",
            "network": "Arbitrum One",
            "bridge_address": "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7",
            "min_deposit_usdc": 5,
            "credits": "the sending wallet's HL account",
            "cex_deposit_supported": False,
            "note": "Withdraw CEX -> your own Arbitrum wallet -> HL bridge.",
        }

    # ----- Discovery helpers --------------------------------------------

    @mcp.tool()
    def hyperliquid_find_best_funding_rates(
        top_n: int = 10, side: str = "short"
    ) -> dict[str, Any]:
        """Rank Hyperliquid perps by carry-friendliness.

        side="short": most positive funding (you earn by being short).
        side="long":  most negative funding (you earn by being long).
        Returns top_n with annualized APR for quick scan.
        """
        meta, ctxs = _info().meta_and_asset_ctxs()
        rows: list[dict[str, Any]] = []
        for asset, ctx in zip(meta.get("universe", []), ctxs):
            try:
                hourly = float(ctx.get("funding", 0.0))
            except (TypeError, ValueError):
                continue
            rows.append({
                "coin": asset.get("name"),
                "hourly": hourly,
                "apr": _annualize_funding(hourly),
                "open_interest": ctx.get("openInterest"),
                "day_ntl_vlm": ctx.get("dayNtlVlm"),
                "max_leverage": asset.get("maxLeverage"),
            })
        rows.sort(key=lambda r: r["hourly"], reverse=(side.lower() == "short"))
        return {"side": side.lower(), "top": rows[:top_n]}

    return 22
