from datetime import datetime, timedelta, timezone
import math
import numpy as np
import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

class TradingAgent:
    def __init__(self, cfg):
        if not cfg["api_key"] or not cfg["secret_key"]:
            raise ValueError("Missing Alpaca API credentials.")
        if not cfg["paper"] and not cfg["live_allowed"]:
            raise ValueError(
                "Live trading is locked. Set PAPER_TRADING=true, or deliberately "
                "set LIVE_TRADING_ALLOWED=true before using a live account."
            )
        self.cfg = cfg
        self.data = StockHistoricalDataClient(cfg["api_key"], cfg["secret_key"])
        self.trading = TradingClient(
            cfg["api_key"], cfg["secret_key"], paper=cfg["paper"]
        )

    def account_snapshot(self):
        a = self.trading.get_account()
        positions = self.trading.get_all_positions()
        return {
            "equity": float(a.equity),
            "last_equity": float(a.last_equity),
            "buying_power": float(a.buying_power),
            "cash": float(a.cash),
            "trading_blocked": bool(a.trading_blocked),
            "open_positions": len(positions),
        }

    def market_open(self):
        return bool(self.trading.get_clock().is_open)

    def bars(self, symbol, lookback_days=5):
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=lookback_days)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
            start=start,
            end=end,
            limit=1000,
        )
        raw = self.data.get_stock_bars(req).df
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.index, pd.MultiIndex):
            try:
                raw = raw.xs(symbol)
            except Exception:
                raw = raw.reset_index()
                raw = raw[raw["symbol"] == symbol].set_index("timestamp")
        return raw.sort_index()

    @staticmethod
    def analyze(df):
        if df is None or len(df) < 60:
            return None
        d = df.copy()
        d["ema9"] = d["close"].ewm(span=9, adjust=False).mean()
        d["ema21"] = d["close"].ewm(span=21, adjust=False).mean()
        typical = (d["high"] + d["low"] + d["close"]) / 3
        d["vwap"] = (typical * d["volume"]).cumsum() / d["volume"].cumsum().replace(0, np.nan)
        d["vol_ma20"] = d["volume"].rolling(20).mean()
        prev_close = d["close"].shift(1)
        tr = pd.concat([
            d["high"] - d["low"],
            (d["high"] - prev_close).abs(),
            (d["low"] - prev_close).abs()
        ], axis=1).max(axis=1)
        d["atr14"] = tr.rolling(14).mean()
        d["high20_prev"] = d["high"].shift(1).rolling(20).max()

        r = d.iloc[-1]
        price = float(r["close"])
        atr = float(r["atr14"]) if pd.notna(r["atr14"]) else 0.0
        score = 0
        reasons = []

        if price > float(r["vwap"]):
            score += 1; reasons.append("above VWAP")
        if float(r["ema9"]) > float(r["ema21"]):
            score += 1; reasons.append("EMA 9 > EMA 21")
        if price > float(r["high20_prev"]):
            score += 1; reasons.append("20-bar breakout")
        if float(r["volume"]) > 1.3 * float(r["vol_ma20"]):
            score += 1; reasons.append("volume expansion")
        if atr > 0 and atr / price < 0.03:
            score += 1; reasons.append("controlled volatility")

        signal = "BUY" if score >= 4 else "WATCH"
        return {
            "price": price,
            "atr": atr,
            "score": score,
            "signal": signal,
            "reasons": ", ".join(reasons) or "No confirmation",
        }

    def scan(self):
        rows = []
        for symbol in self.cfg["watchlist"]:
            try:
                analysis = self.analyze(self.bars(symbol))
                if analysis:
                    rows.append({"symbol": symbol, **analysis})
            except Exception as e:
                rows.append({
                    "symbol": symbol, "price": None, "atr": None,
                    "score": 0, "signal": "ERROR", "reasons": str(e)[:120]
                })
        return pd.DataFrame(rows).sort_values(
            ["score", "symbol"], ascending=[False, True]
        ) if rows else pd.DataFrame()

    def can_open_new_trade(self):
        acct = self.account_snapshot()
        if acct["trading_blocked"]:
            return False, "Broker reports trading_blocked."
        if acct["open_positions"] >= self.cfg["max_open_positions"]:
            return False, "Maximum open positions reached."
        if acct["last_equity"] > 0:
            day_return = (acct["equity"] - acct["last_equity"]) / acct["last_equity"]
            if day_return <= -self.cfg["daily_loss_limit"]:
                return False, "Daily loss limit reached."
        if not self.market_open():
            return False, "Market is closed."
        return True, "OK"

    def size_order(self, price, atr):
        acct = self.account_snapshot()
        if price <= 0 or atr <= 0:
            return 0
        risk_dollars = acct["equity"] * self.cfg["risk_per_trade"]
        assumed_stop_distance = max(1.5 * atr, price * 0.003)
        qty_by_risk = risk_dollars / assumed_stop_distance
        max_notional = min(
            acct["equity"] * self.cfg["max_position_pct"],
            acct["buying_power"] * 0.95
        )
        qty_by_cap = max_notional / price
        qty = math.floor(min(qty_by_risk, qty_by_cap))
        return max(qty, 0)

    def submit_paper_or_live_buy(self, symbol, price, atr):
        ok, reason = self.can_open_new_trade()
        if not ok:
            return {"ok": False, "message": reason}
        qty = self.size_order(price, atr)
        if qty < 1:
            return {"ok": False, "message": "Calculated quantity is below 1 share."}
        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        result = self.trading.submit_order(order_data=order)
        return {
            "ok": True,
            "message": f"Submitted BUY {qty} {symbol}",
            "order_id": str(result.id),
        }

    def close_position(self, symbol):
        result = self.trading.close_position(symbol)
        return str(getattr(result, "id", result))
