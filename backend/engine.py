import os
import time
import traceback
import threading
from datetime import datetime, timedelta
import logging
import json
from database import SessionLocal, Portfolio, Position, Trade, AIInsight, EngineLog
from algorithms import data_fetcher
from ai_agent import generate_trade_insight_core, async_generate_trade_insight_worker
import importlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

# Global lock dictionary to prevent race conditions per algorithm
engine_locks = {}
lock_for_locks = threading.Lock()

def cleanup_old_logs(db):
    """
    Clean up old engine logs if enabled in config.
    Default is disabled (ENABLE_LOG_CLEANUP="false").
    """
    try:
        enable_cleanup = os.getenv("ENABLE_LOG_CLEANUP", "false").lower() in ("true", "1", "yes")
        if not enable_cleanup:
            return
            
        retention_days = int(os.getenv("LOG_RETENTION_DAYS", "30"))
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        deleted_count = db.query(EngineLog).filter(EngineLog.timestamp < cutoff_date).delete(synchronize_session=False)
        if deleted_count > 0:
            db.commit()
            logger.info(f"Cleaned up {deleted_count} old engine logs older than {retention_days} days (before {cutoff_date}).")
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")

def tick_engine(algo_name=None):
    """
    Core paper trading engine loop.
    Supports running a specific algorithm or all of them.
    """
    # Get or create a lock for this specific execution scope
    lock_key = algo_name if algo_name else "ALL"
    with lock_for_locks:
        if lock_key not in engine_locks:
            engine_locks[lock_key] = threading.Lock()
        algo_lock = engine_locks[lock_key]
        
    if not algo_lock.acquire(blocking=False):
        logger.warning(f"Engine tick for {lock_key} is already running. Skipping this concurrent tick request.")
        return
        
    db = SessionLocal()
    try:
        logger.info(f"=== Engine Tick Started for {lock_key} ===")
    
        # 1. Fetch Market Data (Optimization: Only fetch for the specific algo's holdings if algo_name provided)
        query = db.query(Portfolio).filter(Portfolio.is_deleted == 0)
        if algo_name:
            query = query.filter(Portfolio.algorithm_name == algo_name)
        active_portfolios = query.all()
        
        if not active_portfolios:
            logger.warning(f"No active portfolios found for {lock_key}.")
            return
            
        # Get holdings for these specific portfolios
        holding_symbols = []
        for port in active_portfolios:
            positions = db.query(Position).filter(Position.portfolio_id == port.id).all()
            holding_symbols.extend([p.symbol for p in positions])
            # Also get futures positions
            from database import FuturesPosition
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == port.id).all()
            holding_symbols.extend([p.symbol for p in f_positions])
            
        holding_symbols = list(set(holding_symbols))
        
        logger.info(f"Step 1: Fetching current market data for Top 30 + {len(holding_symbols)} held symbols...")
        market_data = data_fetcher.get_market_data(holding_symbols)
        if not market_data:
            logger.error("Failed to fetch market data. Aborting tick.")
            return
            
        logger.info(f"Successfully fetched market data for {len(market_data)} symbols.")
        
        for portfolio in active_portfolios:
            current_algo_name = portfolio.algorithm_name
            if not portfolio.file_name:
                logger.warning(f"Portfolio {current_algo_name} has no file_name. Skipping.")
                continue
            
            try:
                module_name = f"algorithms.{portfolio.file_name.replace('.py', '')}"
                algo_module = importlib.import_module(module_name)
                algo_func = algo_module.get_target_allocations
            except Exception as e:
                logger.error(f"Failed to load algorithm {portfolio.file_name} for {current_algo_name}: {e}")
                continue
                
            logger.info(f"Step 2: Processing algorithm '{current_algo_name}'... Current Balance: ${portfolio.balance_usd:.2f}")
            
            # 3. Get current holdings
            positions = db.query(Position).filter(Position.portfolio_id == portfolio.id).all()
            current_holdings = [p.symbol for p in positions]
            logger.info(f"  Current holdings for {current_algo_name}: {current_holdings}")
            
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
            from database import FuturesTrade
            import inspect
            
            past_trades = db.query(FuturesTrade).filter(
                FuturesTrade.portfolio_id == portfolio.id,
                FuturesTrade.action == "CLOSE"
            ).order_by(FuturesTrade.timestamp.asc()).all()
            
            trade_history = [1 if (t.profit_pct and t.profit_pct > 0) else 0 for t in past_trades]
            
            logger.info(f"Step 3: Calculating target allocations for {current_algo_name}... (Found {len(trade_history)} past trades)")
            
            kwargs = {"current_holdings": current_holdings, "total_value": total_value}
            sig = inspect.signature(algo_func)
            if 'trade_history' in sig.parameters:
                kwargs['trade_history'] = trade_history
            if 'live_execute' in sig.parameters:
                kwargs['live_execute'] = getattr(portfolio, 'execution_type', 'paper') == 'real'
                
            targets, symbol_reasons = algo_func(market_data, **kwargs)
            logger.info(f"  Target Allocations: {targets}")
            
            # Save Engine Log for calculation process
            engine_log = EngineLog(
                portfolio_id=portfolio.id,
                logs_json=json.dumps(symbol_reasons)
            )
            db.add(engine_log)
            db.commit()
            
            # 5. Execute Trades (Sells first to free up cash)
            logger.info(f"Step 4: Executing Trades for {current_algo_name}...")
            # Execute Trades for Futures and Spot
            from database import FuturesPosition, FuturesTrade
            
            # Fetch futures positions
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == portfolio.id).all()
            
            # First, close out any positions (Spot or Futures) where target is 0 or opposite direction
            for sym, target_weight in targets.items():
                current_price = current_prices.get(sym)
                if not current_price: continue
                
                # Spot Closure (Legacy)
                pos = next((p for p in positions if p.symbol == sym), None)
                if pos and target_weight <= 0:
                    profit_pct = ((current_price - pos.avg_entry_price) / pos.avg_entry_price) * 100
                    portfolio.balance_usd += pos.amount * current_price
                    trade = Trade(portfolio_id=portfolio.id, symbol=sym, action="SELL", amount=pos.amount, price=current_price, profit_pct=profit_pct, reason=json.dumps(symbol_reasons.get(sym)) if sym in symbol_reasons else None)
                    db.add(trade)
                    db.delete(pos)
                    db.commit()
                
                # Futures Closure
                f_pos = next((p for p in f_positions if p.symbol == sym), None)
                if f_pos:
                    # If target is 0, or we need to flip direction
                    if target_weight == 0 or (target_weight > 0 and f_pos.direction == 'SHORT') or (target_weight < 0 and f_pos.direction == 'LONG'):
                        profit_pct = ((current_price - f_pos.avg_entry_price) / f_pos.avg_entry_price) * 100 if f_pos.direction == "LONG" else ((f_pos.avg_entry_price - current_price) / f_pos.avg_entry_price) * 100
                        profit_usd = (f_pos.amount * current_price * (profit_pct/100)) # Simplified
                        portfolio.balance_usd += profit_usd
                        
                        f_trade = FuturesTrade(portfolio_id=portfolio.id, symbol=sym, direction=f_pos.direction, action="CLOSE", amount=f_pos.amount, price=current_price, profit_pct=profit_pct, profit_usd=profit_usd, reason=json.dumps(symbol_reasons.get(sym)) if sym in symbol_reasons else None)
                        db.add(f_trade)
                        db.commit()
                        db.refresh(f_trade)
                        
                        # TRIGGER AI INSIGHT
                        if getattr(portfolio, 'is_ai_enabled', 1):
                            threading.Thread(
                                target=async_generate_trade_insight_worker, 
                                args=(f_trade.id, sym, f"CLOSE {f_pos.direction}", profit_pct, f_pos.avg_entry_price, current_price, current_algo_name)
                            ).start()
                            
                        db.delete(f_pos)
                        db.commit()
                        f_positions.remove(f_pos)

            # Next, open new positions
            for sym, target_weight in targets.items():
                current_price = current_prices.get(sym)
                if not current_price or target_weight == 0: continue
                
                target_usd = total_value * abs(target_weight)
                buy_amount = target_usd / current_price
                
                # Is it a futures algorithm?
                if getattr(portfolio, 'trading_type', 'spot') == 'future' or target_weight < 0:
                    f_pos = next((p for p in f_positions if p.symbol == sym), None)
                    if not f_pos:
                        direction = "LONG" if target_weight > 0 else "SHORT"
                        new_f_pos = FuturesPosition(portfolio_id=portfolio.id, symbol=sym, direction=direction, amount=buy_amount, avg_entry_price=current_price, sl=symbol_reasons.get(sym, {}).get("sl"), tp=symbol_reasons.get(sym, {}).get("tp"))
                        db.add(new_f_pos)
                        f_trade = FuturesTrade(portfolio_id=portfolio.id, symbol=sym, direction=direction, action="OPEN", amount=buy_amount, price=current_price, reason=json.dumps(symbol_reasons.get(sym)) if sym in symbol_reasons else None)
                        db.add(f_trade)
                        db.commit()
                else:
                    # Legacy Spot Buy
                    pos = next((p for p in positions if p.symbol == sym), None)
                    if not pos and portfolio.balance_usd >= target_usd * 0.99:
                        portfolio.balance_usd -= target_usd
                        new_pos = Position(portfolio_id=portfolio.id, symbol=sym, amount=buy_amount, avg_entry_price=current_price)
                        db.add(new_pos)
                        trade = Trade(portfolio_id=portfolio.id, symbol=sym, action="BUY", amount=buy_amount, price=current_price, reason=json.dumps(symbol_reasons.get(sym)) if sym in symbol_reasons else None)
                        db.add(trade)
                        db.commit()
                        
        # Step 5: Clean up old logs if enabled
        cleanup_old_logs(db)
        
    except Exception as e:
        logger.error(f"Engine Tick Error: {e}")
        traceback.print_exc()
        if db:
            db.rollback()
    finally:
        if db:
            db.close()
        algo_lock.release()
        
    logger.info(f"=== Engine Tick Completed for {lock_key} ===")

if __name__ == "__main__":
    tick_engine()
