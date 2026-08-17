import streamlit as st
import pandas as pd
from streamlit_autorefresh import st_autorefresh

from config import get_config
from trader import TradingAgent

st.set_page_config(page_title="AI Day Trader", page_icon="📈", layout="wide")
st.title("AI Day Trader")
st.caption("Market scanner + guarded Alpaca execution. Paper trading is the intended default.")

cfg = get_config()

with st.sidebar:
    st.header("Controls")
    auto = st.toggle("Auto-refresh dashboard", value=False)
    execute_enabled = st.toggle(
        "Enable order buttons",
        value=False,
        help="This only enables UI buttons. Broker/environment safety locks still apply."
    )
    st.write("Mode:", "PAPER" if cfg["paper"] else "LIVE")
    st.write("Watchlist:", ", ".join(cfg["watchlist"]))
    st.write(f"Risk/trade: {cfg['risk_per_trade']*100:.2f}%")
    st.write(f"Daily loss cutoff: {cfg['daily_loss_limit']*100:.2f}%")
    if not cfg["paper"]:
        st.error("LIVE MODE. Real money can be lost.")

if auto:
    st_autorefresh(interval=60_000, key="market_refresh")

try:
    agent = TradingAgent(cfg)
except Exception as e:
    st.error(str(e))
    st.info("Add Alpaca PAPER API credentials to Streamlit Secrets or local environment variables.")
    st.stop()

acct = agent.account_snapshot()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Equity", f"${acct['equity']:,.2f}")
c2.metric("Buying power", f"${acct['buying_power']:,.2f}")
c3.metric("Cash", f"${acct['cash']:,.2f}")
c4.metric("Open positions", acct["open_positions"])

market_status = "OPEN" if agent.market_open() else "CLOSED"
st.subheader(f"Market: {market_status}")

if st.button("Run market scan", type="primary") or "scan" not in st.session_state:
    with st.spinner("Scanning watchlist..."):
        st.session_state.scan = agent.scan()

scan = st.session_state.get("scan", pd.DataFrame())
if scan.empty:
    st.warning("No scan data returned yet.")
else:
    display = scan.copy()
    if "price" in display:
        display["price"] = display["price"].map(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
    if "atr" in display:
        display["atr"] = display["atr"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")
    st.dataframe(display, use_container_width=True, hide_index=True)

    candidates = scan[scan["signal"] == "BUY"]
    st.subheader("Qualified candidates")
    if candidates.empty:
        st.info("No symbol currently meets the strategy threshold.")
    else:
        for _, row in candidates.iterrows():
            symbol = row["symbol"]
            cols = st.columns([2,2,4,2])
            cols[0].strong(symbol)
            cols[1].write(f"${row['price']:.2f}")
            cols[2].write(row["reasons"])
            if cols[3].button(f"Buy {symbol}", disabled=not execute_enabled, key=f"buy_{symbol}"):
                result = agent.submit_paper_or_live_buy(symbol, row["price"], row["atr"])
                if result["ok"]:
                    st.success(result["message"])
                else:
                    st.warning(result["message"])

st.divider()
st.subheader("Positions")
positions = agent.trading.get_all_positions()
if not positions:
    st.write("No open positions.")
else:
    pos_rows = []
    for p in positions:
        pos_rows.append({
            "symbol": p.symbol,
            "qty": p.qty,
            "market_value": p.market_value,
            "unrealized_pl": p.unrealized_pl,
            "unrealized_plpc": p.unrealized_plpc,
        })
    st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)
    if execute_enabled:
        close_symbol = st.selectbox("Close a position", [p.symbol for p in positions])
        if st.button("Close selected position"):
            oid = agent.close_position(close_symbol)
            st.success(f"Close request submitted for {close_symbol}. Order: {oid}")

st.caption(
    "Signals are rule-based and experimental. Paper results do not guarantee live results. "
    "Slippage, gaps, outages, and market conditions can materially change outcomes."
)
