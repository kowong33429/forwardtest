import os
import time
import traceback
import threading
from datetime import datetime, timedelta
import logging
import json
import numpy as np
from database import SessionLocal, Portfolio, Position, Trade, AIInsight, EngineLog, FuturesPosition, FuturesTrade
from services import binance_service, mt5_service
import inspect

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NpEncoder, self).default(obj)

def safe_dumps(data):
    if data is None:
        return None
    return json.dumps(data, cls=NpEncoder)

from algorithms import data_fetcher
from agents.ai_agent import async_generate_trade_insight_worker
from agents.ai_agent import async_generate_trade_insight_worker
import importlib
from logger_setup import setup_logger, set_trace_id
import uuid

logger = setup_logger("TradingEngine")

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
        
    set_trace_id(f"Tick-{algo_name.replace(' ', '') if algo_name else 'ALL'}-{str(uuid.uuid4())[:6]}")
        
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
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == port.id).all()
            holding_symbols.extend([p.symbol for p in f_positions])
            
        holding_symbols = list(set(holding_symbols))
        
        logger.info(f"Step 1: Fetching current market data...")
        market_data_by_type = {}
        for port in active_portfolios:
            algo_type = getattr(port, "algo_type", "crypto")
            if algo_type not in market_data_by_type:
                market_data_by_type[algo_type] = []
                
            positions = db.query(Position).filter(Position.portfolio_id == port.id).all()
            market_data_by_type[algo_type].extend([p.symbol for p in positions])
            
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == port.id).all()
            market_data_by_type[algo_type].extend([p.symbol for p in f_positions])

        all_market_data = {}
        for algo_type, symbols in market_data_by_type.items():
            symbols = list(set(symbols))
            data = data_fetcher.get_market_data(symbols, algo_type=algo_type)
            if data:
                all_market_data.update(data)
                
        if not all_market_data:
            logger.error("Failed to fetch market data. Aborting tick.")
            return
            
        logger.info(f"Successfully fetched market data for {len(all_market_data)} symbols.")
        market_data = all_market_data
        
        for portfolio in active_portfolios:
            current_algo_name = portfolio.algorithm_name
            if not portfolio.file_name:
                logger.warning(f"Portfolio {current_algo_name} has no file_name. Skipping.")
                continue
            
            algo_type = getattr(portfolio, 'algo_type', 'crypto')
            if algo_type == 'forex':
                is_open, close_reason = mt5_service.is_forex_market_open()
                if not is_open:
                    logger.info(f"Skipping {current_algo_name}: {close_reason}")
                    engine_log = EngineLog(
                        portfolio_id=portfolio.id,
                        logs_json=safe_dumps({"SYSTEM": {"decision_logic": close_reason}})
                    )
                    db.add(engine_log)
                    db.commit()
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
                current_prices[sym] = float(df['close'].iloc[-1])
                
            for pos in positions:
                if pos.symbol in current_prices:
                    total_value += pos.amount * current_prices[pos.symbol]
                    
            logger.info(f"  Total Estimated Value: ${total_value:.2f}")
            
            # 3.5. Execute pending Stop Loss & Take Profit (Paper Trading Simulation)
            for pos in positions[:]:
                if pos.symbol in current_prices:
                    current_price = current_prices[pos.symbol]
                    gain_pct = (current_price - pos.avg_entry_price) / pos.avg_entry_price
                    
                    # Hardcoded defaults for V9 / Spot algorithms (-10% SL, +30% TP)
                    # (Bypass for v5 algorithms so they can manage their own exits)
                    is_v5 = current_algo_name and "v5" in current_algo_name.lower()
                    if not is_v5 and (gain_pct <= -0.10 or gain_pct >= 0.30):
                        reason_msg = f"TAKE PROFIT (+{gain_pct*100:.1f}%)" if gain_pct >= 0.30 else f"STOP LOSS ({gain_pct*100:.1f}%)"
                        logger.info(f"  {reason_msg} triggered for {pos.symbol} at {current_price:.4f}")
                        portfolio.balance_usd += pos.amount * current_price
                        
                        trade = Trade(portfolio_id=portfolio.id, symbol=pos.symbol, action="SELL", amount=pos.amount, price=current_price, profit_pct=gain_pct*100, reason=reason_msg)
                        db.add(trade)
                        db.delete(pos)
                        db.commit()
                        
                        # TRIGGER AI INSIGHT
                        if getattr(portfolio, 'is_ai_enabled', 1):
                            threading.Thread(
                                target=async_generate_trade_insight_worker, 
                                args=(trade.id, pos.symbol, "SELL", gain_pct*100, pos.avg_entry_price, current_price, current_algo_name)
                            ).start()
                        
                        positions.remove(pos)
                        if pos.symbol in current_holdings:
                            current_holdings.remove(pos.symbol)
            # 3.6. Execute pending Stop Loss & Take Profit for Futures (Paper Trading Simulation)
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == portfolio.id).all()
            for f_pos in f_positions[:]:
                if f_pos.symbol in current_prices:
                    current_price = current_prices[f_pos.symbol]
                    close_reason = None
                    
                    if f_pos.direction == "LONG":
                        if f_pos.sl and current_price <= f_pos.sl:
                            close_reason = "STOP LOSS"
                        elif f_pos.tp and current_price >= f_pos.tp:
                            close_reason = "TAKE PROFIT"
                    else: # SHORT
                        if f_pos.sl and current_price >= f_pos.sl:
                            close_reason = "STOP LOSS"
                        elif f_pos.tp and current_price <= f_pos.tp:
                            close_reason = "TAKE PROFIT"
                            
                    if close_reason:
                        profit_pct = ((current_price - f_pos.avg_entry_price) / f_pos.avg_entry_price) * 100 if f_pos.direction == "LONG" else ((f_pos.avg_entry_price - current_price) / f_pos.avg_entry_price) * 100
                        logger.info(f"  Futures {close_reason} ({profit_pct:.1f}%) triggered for {f_pos.symbol} at {current_price:.4f}")
                        
                        profit_usd = f_pos.amount * (current_price - f_pos.avg_entry_price) if f_pos.direction == "LONG" else f_pos.amount * (f_pos.avg_entry_price - current_price)
                        portfolio.balance_usd += profit_usd
                        
                        f_trade = FuturesTrade(portfolio_id=portfolio.id, symbol=f_pos.symbol, direction=f_pos.direction, action="CLOSE", amount=f_pos.amount, price=current_price, profit_pct=profit_pct, profit_usd=profit_usd, reason=f"{close_reason} ({profit_pct:.1f}%)")
                        db.add(f_trade)
                        db.commit()
                        db.refresh(f_trade)
                        
                        # TRIGGER AI INSIGHT
                        if getattr(portfolio, 'is_ai_enabled', 1):
                            threading.Thread(
                                target=async_generate_trade_insight_worker, 
                                args=(f_trade.id, f_pos.symbol, f"CLOSE {f_pos.direction}", profit_pct, f_pos.avg_entry_price, current_price, current_algo_name)
                            ).start()
                            
                        db.delete(f_pos)
                        db.commit()
                        f_positions.remove(f_pos)
                        if f_pos.symbol in current_holdings:
                            current_holdings.remove(f_pos.symbol)
            
            # 4. Get target allocations
            
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
                logs_json=safe_dumps(symbol_reasons)
            )
            db.add(engine_log)
            db.commit()
            
            # 5. Execute Trades (Sells first to free up cash)
            logger.info(f"Step 4: Executing Trades for {current_algo_name}...")
            # Execute Trades for Futures and Spot
            
            # Fetch futures positions
            f_positions = db.query(FuturesPosition).filter(FuturesPosition.portfolio_id == portfolio.id).all()
            
            # First, close out any positions (Spot or Futures) where target is 0 or opposite direction or fell out of targets
            # Spot Closure (Legacy)
            for pos in positions[:]:
                target_weight = float(targets.get(pos.symbol, 0.0))
                current_price = current_prices.get(pos.symbol)
                
                if current_price and target_weight <= 0:
                    profit_pct = ((current_price - pos.avg_entry_price) / pos.avg_entry_price) * 100
                    
                    if getattr(portfolio, 'execution_type', 'paper') == 'real':
                        algo_type = getattr(portfolio, 'algo_type', 'crypto')
                        if algo_type == 'crypto':
                            binance_service.execute_trade(pos.symbol, "SELL", pos.amount)
                            
                    portfolio.balance_usd += pos.amount * current_price
                    trade = Trade(portfolio_id=portfolio.id, symbol=pos.symbol, action="SELL", amount=pos.amount, price=current_price, profit_pct=profit_pct, reason=safe_dumps(symbol_reasons.get(pos.symbol)))
                    db.add(trade)
                    db.delete(pos)
                    db.commit()
                    
                    # TRIGGER AI INSIGHT
                    if getattr(portfolio, 'is_ai_enabled', 1):
                        threading.Thread(
                            target=async_generate_trade_insight_worker, 
                            args=(trade.id, pos.symbol, "SELL", profit_pct, pos.avg_entry_price, current_price, current_algo_name)
                        ).start()
            
            # Futures Closure
            for f_pos in f_positions[:]:
                target_weight = float(targets.get(f_pos.symbol, 0.0))
                current_price = current_prices.get(f_pos.symbol)
                
                if current_price:
                    # If target is 0, or we need to flip direction
                    if target_weight == 0 or (target_weight > 0 and f_pos.direction == 'SHORT') or (target_weight < 0 and f_pos.direction == 'LONG'):
                        profit_pct = ((current_price - f_pos.avg_entry_price) / f_pos.avg_entry_price) * 100 if f_pos.direction == "LONG" else ((f_pos.avg_entry_price - current_price) / f_pos.avg_entry_price) * 100
                        profit_usd = f_pos.amount * (current_price - f_pos.avg_entry_price) if f_pos.direction == "LONG" else f_pos.amount * (f_pos.avg_entry_price - current_price)
                        
                        if getattr(portfolio, 'execution_type', 'paper') == 'real':
                            algo_type = getattr(portfolio, 'algo_type', 'crypto')
                            close_dir = "LONG" if f_pos.direction == "SHORT" else "SHORT"
                            if algo_type == 'crypto':
                                binance_service.execute_futures_trade(f_pos.symbol, close_dir, f_pos.amount)
                            elif algo_type == 'forex':
                                mt5_service.execute_trade(f_pos.symbol, close_dir, f_pos.amount, sl=0, tp=0, comment="Close position")
                                
                        portfolio.balance_usd += profit_usd
                        
                        f_trade = FuturesTrade(portfolio_id=portfolio.id, symbol=f_pos.symbol, direction=f_pos.direction, action="CLOSE", amount=f_pos.amount, price=current_price, profit_pct=profit_pct, profit_usd=profit_usd, reason=safe_dumps(symbol_reasons.get(f_pos.symbol)))
                        db.add(f_trade)
                        db.commit()
                        db.refresh(f_trade)
                        
                        # TRIGGER AI INSIGHT
                        if getattr(portfolio, 'is_ai_enabled', 1):
                            threading.Thread(
                                target=async_generate_trade_insight_worker, 
                                args=(f_trade.id, f_pos.symbol, f"CLOSE {f_pos.direction}", profit_pct, f_pos.avg_entry_price, current_price, current_algo_name)
                            ).start()
                            
                        db.delete(f_pos)
                        db.commit()
                        f_positions.remove(f_pos)

            # Next, open new positions
            for sym, target_weight in targets.items():
                target_weight = float(target_weight)
                current_price = current_prices.get(sym)
                if not current_price and sym in symbol_reasons and 'price' in symbol_reasons[sym]:
                    current_price = symbol_reasons[sym]['price']
                    
                if not current_price or target_weight == 0: continue
                
                target_usd = total_value * abs(target_weight)
                buy_amount = target_usd / current_price
                
                # Is it a futures algorithm?
                if getattr(portfolio, 'trading_type', 'spot') == 'future' or target_weight < 0:
                    f_pos = next((p for p in f_positions if p.symbol == sym), None)
                    if not f_pos:
                        direction = "LONG" if target_weight > 0 else "SHORT"
                        
                        if getattr(portfolio, 'execution_type', 'paper') == 'real':
                            algo_type = getattr(portfolio, 'algo_type', 'crypto')
                            if algo_type == 'crypto':
                                binance_service.execute_futures_trade(sym, direction, buy_amount)
                            elif algo_type == 'forex':
                                mt5_service.execute_trade(sym, direction, buy_amount, sl=symbol_reasons.get(sym, {}).get("sl", 0), tp=symbol_reasons.get(sym, {}).get("tp", 0), comment="Open position")
                                
                        new_f_pos = FuturesPosition(portfolio_id=portfolio.id, symbol=sym, direction=direction, amount=buy_amount, avg_entry_price=current_price, sl=symbol_reasons.get(sym, {}).get("sl"), tp=symbol_reasons.get(sym, {}).get("tp"))
                        db.add(new_f_pos)
                        f_trade = FuturesTrade(portfolio_id=portfolio.id, symbol=sym, direction=direction, action="OPEN", amount=buy_amount, price=current_price, reason=safe_dumps(symbol_reasons.get(sym)))
                        db.add(f_trade)
                        db.commit()
                else:
                    # Legacy Spot Buy
                    pos = next((p for p in positions if p.symbol == sym), None)
                    if not pos and portfolio.balance_usd >= target_usd * 0.99:
                        portfolio.balance_usd -= target_usd
                        
                        if getattr(portfolio, 'execution_type', 'paper') == 'real':
                            algo_type = getattr(portfolio, 'algo_type', 'crypto')
                            if algo_type == 'crypto':
                                binance_service.execute_trade(sym, "LONG", buy_amount)
                                
                        new_pos = Position(portfolio_id=portfolio.id, symbol=sym, amount=buy_amount, avg_entry_price=current_price)
                        db.add(new_pos)
                        trade = Trade(portfolio_id=portfolio.id, symbol=sym, action="BUY", amount=buy_amount, price=current_price, reason=safe_dumps(symbol_reasons.get(sym)))
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
