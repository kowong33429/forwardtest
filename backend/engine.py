import time
import traceback
import threading
from datetime import datetime
import logging
import json
from database import SessionLocal, Portfolio, Position, Trade, AIInsight, EngineLog
from algorithms import data_fetcher, v4, v5_1
from ai_agent import generate_trade_insight

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

ALGORITHMS = {
    "V4.0 Aggressive": v4.get_target_allocations,
    "V5.1 God Mode": v5_1.get_target_allocations
}

# Global lock to prevent race conditions during Force Tick (Double Spending)
engine_lock = threading.Lock()

def tick_engine():
    """
    Core paper trading engine loop.
    """
    if not engine_lock.acquire(blocking=False):
        logger.warning("Engine tick is already running. Skipping this concurrent tick request.")
        return
        
    try:
        logger.info("=== Engine Tick Started ===")
    
    # 1. Fetch Market Data
    logger.info("Step 1: Fetching current market data...")
    market_data = data_fetcher.get_market_data()
    if not market_data:
        logger.error("Failed to fetch market data. Aborting tick.")
        return
        
    logger.info(f"Successfully fetched market data for {len(market_data)} symbols.")
        
    db = SessionLocal()
    
    try:
        for algo_name, algo_func in ALGORITHMS.items():
            # 2. Get or create portfolio
            portfolio = db.query(Portfolio).filter(Portfolio.algorithm_name == algo_name).first()
            if not portfolio:
                portfolio = Portfolio(algorithm_name=algo_name, balance_usd=10000.0)
                db.add(portfolio)
                db.commit()
                db.refresh(portfolio)
                
            logger.info(f"Step 2: Processing algorithm '{algo_name}'... Current Balance: ${portfolio.balance_usd:.2f}")
            
            # 3. Get current holdings
            positions = db.query(Position).filter(Position.portfolio_id == portfolio.id).all()
            current_holdings = [p.symbol for p in positions]
            logger.info(f"  Current holdings for {algo_name}: {current_holdings}")
            
            # Calculate total portfolio value (cash + assets)
            total_value = portfolio.balance_usd
            current_prices = {}
            for sym, df in market_data.items():
                current_prices[sym] = df['close'].iloc[-1]
                
            for pos in positions:
                if pos.symbol in current_prices:
                    total_value += pos.amount * current_prices[pos.symbol]
                    
            logger.info(f"  Total Estimated Value: ${total_value:.2f}")
            
            # 4. Get target allocations
            logger.info(f"Step 3: Calculating target allocations for {algo_name}...")
            targets, details = algo_func(market_data, current_holdings=current_holdings)
            logger.info(f"  Target Allocations: {targets}")
            
            # Save Engine Log for calculation process
            engine_log = EngineLog(
                portfolio_id=portfolio.id,
                logs_json=json.dumps(details)
            )
            db.add(engine_log)
            db.commit()
            
            # 5. Execute Trades (Sells first to free up cash)
            logger.info(f"Step 4: Executing Trades for {algo_name}...")
            # Find positions not in targets, or needing reduction
            for pos in positions:
                sym = pos.symbol
                current_price = current_prices.get(sym)
                if not current_price: continue
                
                target_weight = targets.get(sym, 0.0)
                target_usd = total_value * target_weight
                current_usd = pos.amount * current_price
                
                # If target is 0, liquidate fully
                if target_weight == 0:
                    profit_pct = ((current_price - pos.avg_entry_price) / pos.avg_entry_price) * 100
                    logger.info(f"  [SELL] Liquidating {sym} at ${current_price:.4f} (Profit: {profit_pct:.2f}%)")
                    
                    portfolio.balance_usd += pos.amount * current_price
                    
                    trade = Trade(
                        portfolio_id=portfolio.id,
                        symbol=sym,
                        action="SELL",
                        amount=pos.amount,
                        price=current_price,
                        profit_pct=profit_pct
                    )
                    db.add(trade)
                    db.commit()
                    db.refresh(trade)
                    
                    # TRIGGER AI INSIGHT
                    insight_data = generate_trade_insight(sym, "SELL", profit_pct, pos.avg_entry_price, current_price, algo_name)
                    insight = AIInsight(
                        trade_id=trade.id,
                        summary=insight_data.get("summary", ""),
                        macro_context=insight_data.get("macro_context", ""),
                        lessons_learned=insight_data.get("lessons_learned", "")
                    )
                    db.add(insight)
                    
                    db.delete(pos)
                    db.commit()
            
            # Execute Buys
            for sym, target_weight in targets.items():
                if target_weight > 0:
                    current_price = current_prices.get(sym)
                    if not current_price: continue
                    
                    target_usd = total_value * target_weight
                    
                    # Check if we already have it
                    pos = db.query(Position).filter(Position.portfolio_id == portfolio.id, Position.symbol == sym).first()
                    current_usd = pos.amount * current_price if pos else 0.0
                    
                    # If we need to buy more (we only do full rebalance for new entries to keep it simple)
                    if not pos and portfolio.balance_usd >= target_usd * 0.99: # 1% margin
                        buy_amount = target_usd / current_price
                        portfolio.balance_usd -= target_usd
                        
                        logger.info(f"  [BUY] Buying {sym} at ${current_price:.4f} for ${target_usd:.2f}")
                        
                        trade = Trade(
                            portfolio_id=portfolio.id,
                            symbol=sym,
                            action="BUY",
                            amount=buy_amount,
                            price=current_price
                        )
                        db.add(trade)
                        
                        new_pos = Position(
                            portfolio_id=portfolio.id,
                            symbol=sym,
                            amount=buy_amount,
                            avg_entry_price=current_price
                        )
                        db.add(new_pos)
                        db.commit()
                        
    except Exception as e:
        logger.error(f"Engine Tick Error: {e}")
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()
        engine_lock.release()
        
    logger.info("=== Engine Tick Completed ===")

if __name__ == "__main__":
    tick_engine()
