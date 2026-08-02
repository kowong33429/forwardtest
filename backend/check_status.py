import os
import json
from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, Portfolio, Position, Trade, EngineLog
from algorithms import data_fetcher
import importlib

def main():
    db = SessionLocal()
    try:
        print("=== 1. PORTFOLIOS ===")
        portfolios = db.query(Portfolio).all()
        for p in portfolios:
            print(f"ID: {p.id}, Name: '{p.algorithm_name}', File: '{p.file_name}', Balance: ${p.balance_usd}, Hidden: {p.is_hidden}, Deleted: {p.is_deleted}")
            
        print("\n=== 2. POSITIONS ===")
        positions = db.query(Position).all()
        print(f"Total positions in DB: {len(positions)}")
        for pos in positions:
            print(f"ID: {pos.id}, PortID: {pos.portfolio_id}, Symbol: {pos.symbol}, Amount: {pos.amount}, Entry: ${pos.avg_entry_price}")
            
        print("\n=== 3. TRADES (Latest 10) ===")
        trades = db.query(Trade).order_by(Trade.timestamp.desc()).limit(10).all()
        print(f"Total trades fetched: {len(trades)}")
        for t in trades:
            print(f"ID: {t.id}, PortID: {t.portfolio_id}, Time: {t.timestamp}, Action: {t.action}, Symbol: {t.symbol}, Amount: {t.amount}, Price: ${t.price}, Profit: {t.profit_pct}%")

        print("\n=== 4. ENGINE LOGS (Latest 5) ===")
        logs = db.query(EngineLog).order_by(EngineLog.timestamp.desc()).limit(5).all()
        print(f"Total Engine Logs: {len(logs)}")
        for l in logs:
            print(f"ID: {l.id}, PortID: {l.portfolio_id}, Time: {l.timestamp}")
            try:
                parsed = json.loads(l.logs_json)
                print(f"  Logs JSON: {json.dumps(parsed, indent=2)}")
            except:
                print(f"  Raw Log: {l.logs_json[:300]}")

        print("\n=== 5. CHECKING MARKET DATA & ALGORITHMS LOGIC LIVE ===")
        all_positions = db.query(Position).all()
        holding_symbols = list(set([p.symbol for p in all_positions]))
        market_data = data_fetcher.get_market_data(holding_symbols)
        print(f"Market data fetched for {len(market_data)} symbols.")
        
        if 'BTCUSDT' in market_data:
            btc_df = market_data['BTCUSDT']
            btc_price = btc_df['close'].iloc[-1]
            btc_sma200 = btc_df['close'].rolling(window=200).mean().iloc[-1] if len(btc_df) >= 200 else None
            print(f"BTC Candles count: {len(btc_df)}")
            print(f"BTC Current Price: {btc_price}")
            print(f"BTC SMA200 (4h): {btc_sma200}")
            if btc_sma200:
                print(f"BTC Regime: {'BULL' if btc_price > btc_sma200 else 'BEAR'}")

        for p in portfolios:
            if not p.file_name: continue
            module_name = f"algorithms.{p.file_name.replace('.py', '')}"
            try:
                algo_mod = importlib.import_module(module_name)
                targets, reasons = algo_mod.get_target_allocations(market_data, current_holdings=[], total_value=p.balance_usd)
                print(f"\nLive Allocation check for {p.algorithm_name} ({p.file_name}):")
                print(f"  Targets: {targets}")
                print(f"  Reasons: {json.dumps(reasons, indent=2)}")
            except Exception as e:
                print(f"Error testing {p.file_name}: {e}")

    finally:
        db.close()

if __name__ == "__main__":
    main()
