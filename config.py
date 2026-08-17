import os

def _secret(name, default=None):
    # Works locally with environment variables and on Streamlit Cloud with st.secrets.
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name, default)

def get_config():
    watchlist = _secret("WATCHLIST", "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMZN,META")
    return {
        "api_key": _secret("ALPACA_API_KEY", ""),
        "secret_key": _secret("ALPACA_SECRET_KEY", ""),
        "paper": _secret("PAPER_TRADING", "true").lower() == "true",
        "live_allowed": _secret("LIVE_TRADING_ALLOWED", "false").lower() == "true",
        "watchlist": [s.strip().upper() for s in watchlist.split(",") if s.strip()],
        "risk_per_trade": float(_secret("RISK_PER_TRADE", "0.003")),
        "max_position_pct": float(_secret("MAX_POSITION_PCT", "0.10")),
        "max_open_positions": int(_secret("MAX_OPEN_POSITIONS", "3")),
        "daily_loss_limit": float(_secret("DAILY_LOSS_LIMIT", "0.015")),
    }
