import logging
import traceback
import time
import os
from database import SessionLocal, AIInsight, FuturesAIInsight, Trade, FuturesTrade, Portfolio
from algorithms.data_fetcher import fetch_klines

from . import ai_agent_crypto
from . import ai_agent_forex
from . import ai_agent_stock

# Also import optimization tools that were in the original ai_agent.py
# For AI 1.2, we'll route to crypto for now as requested or keep it simple.
# To keep this router fully compatible with engine.py, we also export necessary functions
from .ai_agent_crypto import (
    run_weekly_optimizer, 
    generate_trade_insight_core as crypto_generate_insight
)
from logger_setup import setup_logger, set_trace_id
import uuid

logger = setup_logger("AIAgentRouter")

def read_algo_source(file_name: str) -> str:
    # helper from original ai_agent
    try:
        if file_name:
            filepath = os.path.join("algorithms", file_name)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return f.read()
    except Exception as e:
        logger.error(f"Error reading algo source: {e}")
    return ""

def async_generate_trade_insight_worker(trade_id: int, symbol: str, action: str, profit_pct: float, entry_price: float, exit_price: float, algorithm: str):
    """
    AI 1.1 Background Worker. Retries up to 3 times before giving up.
    Routes to the specialized AI agent based on algo_type.
    """
    set_trace_id(f"AIWorker-{trade_id}-{str(uuid.uuid4())[:4]}")
    logger.info(f"AI 1.1 Worker started for trade_id {trade_id} / {symbol}")
    retries = 0
    max_retries = 3
    while retries < max_retries:
        try:
            db = SessionLocal()
            algo_source = ""
            ohlc_data = ""
            algo_type = "crypto"
            is_futures = False
            trade = None
            
            try:
                # First try spot Trade
                trade = db.query(Trade).filter(Trade.id == trade_id).first()
                if not trade:
                    # Try FuturesTrade
                    trade = db.query(FuturesTrade).filter(FuturesTrade.id == trade_id).first()
                    is_futures = True
                
                limit = 30
                if trade and trade.portfolio:
                    algo_type = getattr(trade.portfolio, "algo_type", "crypto")
                    if trade.portfolio.file_name:
                        algo_source = read_algo_source(trade.portfolio.file_name)
                        
                    # Find the corresponding OPEN/BUY trade to calculate holding duration
                    if not is_futures:
                        buy_trade = db.query(Trade).filter(
                            Trade.portfolio_id == trade.portfolio_id,
                            Trade.symbol == trade.symbol,
                            Trade.action == "BUY",
                            Trade.timestamp < trade.timestamp
                        ).order_by(Trade.timestamp.desc()).first()
                    else:
                        buy_trade = db.query(FuturesTrade).filter(
                            FuturesTrade.portfolio_id == trade.portfolio_id,
                            FuturesTrade.symbol == trade.symbol,
                            FuturesTrade.action == "OPEN",
                            FuturesTrade.timestamp < trade.timestamp
                        ).order_by(FuturesTrade.timestamp.desc()).first()
                        
                    if buy_trade:
                        duration = trade.timestamp - buy_trade.timestamp
                        duration_hours = duration.total_seconds() / 3600
                        calculated_limit = int((duration_hours / 4) + 10)
                        limit = min(max(calculated_limit, 30), 1000)
                    
                df = fetch_klines(symbol, interval="4h", limit=limit, algo_type=algo_type)
                if df is not None and not df.empty:
                    ohlc_data = df.to_string()
            except Exception as e:
                logger.error(f"Error fetching extra context for AI 1.1: {e}")
            finally:
                db.close()
                
            # Route to specialized agent
            if algo_type == "forex":
                insight_data = ai_agent_forex.generate_trade_insight_core(symbol, action, profit_pct, entry_price, exit_price, algorithm, algo_source, ohlc_data)
            elif algo_type == "stock":
                insight_data = ai_agent_stock.generate_trade_insight_core(symbol, action, profit_pct, entry_price, exit_price, algorithm, algo_source, ohlc_data)
            else:
                insight_data = ai_agent_crypto.generate_trade_insight_core(symbol, action, profit_pct, entry_price, exit_price, algorithm, algo_source, ohlc_data)
            
            db = SessionLocal()
            try:
                if not is_futures:
                    insight = AIInsight(
                        trade_id=trade_id,
                        summary=insight_data.get("summary", ""),
                        macro_context=insight_data.get("macro_context", ""),
                        lessons_learned=insight_data.get("lessons_learned", "")
                    )
                else:
                    insight = FuturesAIInsight(
                        futures_trade_id=trade_id,
                        summary=insight_data.get("summary", ""),
                        macro_context=insight_data.get("macro_context", ""),
                        lessons_learned=insight_data.get("lessons_learned", "")
                    )
                db.add(insight)
                db.commit()
                logger.info(f"Successfully generated and saved AI insight for trade {trade_id}")
                break # Exit retry loop on success
            except Exception as e:
                logger.error(f"Error saving AI insight to DB: {e}")
                db.rollback()
                raise e
            finally:
                db.close()
                
        except Exception as e:
            retries += 1
            if retries >= max_retries:
                logger.error(f"AI Worker permanently failed for trade {trade_id} after {max_retries} attempts. Error: {e}")
                break
            logger.error(f"AI Worker failed for trade {trade_id} (Attempt {retries}/{max_retries}), retrying in 10 minutes... Error: {e}")
            traceback.print_exc()
            time.sleep(600)
