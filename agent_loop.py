import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import get_config
from trader import TradingAgent

NY = ZoneInfo("America/New_York")

def run_once(agent):
    if not agent.market_open():
        print("Market closed.")
        return
    allowed, reason = agent.can_open_new_trade()
    if not allowed:
        print("No new trade:", reason)
        return

    scan = agent.scan()
    if scan.empty:
        print("No signals.")
        return

    candidates = scan[scan["signal"] == "BUY"].sort_values("score", ascending=False)
    if candidates.empty:
        print("No qualified candidates.")
        return

    # Conservative behavior: at most one new trade per cycle.
    row = candidates.iloc[0]
    result = agent.submit_paper_or_live_buy(row["symbol"], row["price"], row["atr"])
    print(datetime.now(NY).isoformat(), result)

def main():
    cfg = get_config()
    agent = TradingAgent(cfg)
    print("Starting", "PAPER" if cfg["paper"] else "LIVE", "agent.")
    while True:
        try:
            run_once(agent)
        except Exception as e:
            print("Cycle error:", repr(e))
        time.sleep(300)  # 5-minute cycle

if __name__ == "__main__":
    main()
