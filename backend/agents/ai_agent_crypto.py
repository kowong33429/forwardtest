import os
from google import genai
import requests
import traceback
import logging
from database import SessionLocal, AIInsight, Trade, Portfolio, DailyOptimizationResult
from algorithms.data_fetcher import fetch_klines
from algorithms import backtester
import importlib
import time
import threading
import json
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIAgent")

def fetch_crypto_news():
    try:
        url = "https://cryptopanic.com/api/v1/posts/?public=true"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            news_titles = [post["title"] for post in results[:5]]
            return " | ".join(news_titles)
        else:
            return "No breaking news found."
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return f"Error fetching news: {e}"

def fetch_macro_context():
    api_key = os.getenv("CMC_API_KEY")
    if not api_key:
        return "Macro data unavailable (Missing CMC_API_KEY)."
    
    url = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key,
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json().get("data", {})
            quote = data.get("quote", {}).get("USD", {})
            
            total_mcap = quote.get("total_market_cap", 0)
            vol_24h = quote.get("total_volume_24h", 0)
            btc_dom = data.get("btc_dominance", 0)
            
            return f"Total Market Cap: ${total_mcap:,.0f} | 24h Volume: ${vol_24h:,.0f} | BTC Dominance: {btc_dom:.2f}%"
        else:
            return f"Error fetching macro data: {response.status_code}"
    except Exception as e:
        logger.error(f"Error fetching macro context: {e}")
        return f"Exception fetching macro data: {e}"

def fetch_coin_fundamentals(symbol: str):
    api_key = os.getenv("CMC_API_KEY")
    if not api_key:
        return "Fundamental data unavailable (Missing CMC_API_KEY)."
        
    url_quotes = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
    url_info = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
    
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': api_key,
    }
    
    clean_symbol = symbol.replace("USDT", "").replace("BUSD", "")
    if not clean_symbol:
        clean_symbol = symbol
        
    params = {'symbol': clean_symbol}
    result = []
    
    try:
        res_q = requests.get(url_quotes, headers=headers, params=params, timeout=5)
        if res_q.status_code == 200:
            data = res_q.json().get("data", {}).get(clean_symbol, {})
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            quote = data.get("quote", {}).get("USD", {})
            
            fdv = quote.get("fully_diluted_market_cap")
            circ_supply = data.get("circulating_supply")
            
            if fdv is not None: result.append(f"FDV: ${fdv:,.0f}")
            if circ_supply is not None: result.append(f"Circulating Supply: {circ_supply:,.0f}")
            
        res_i = requests.get(url_info, headers=headers, params=params, timeout=5)
        if res_i.status_code == 200:
            data = res_i.json().get("data", {}).get(clean_symbol, [])
            if isinstance(data, list) and len(data) > 0:
                coin_info = data[0]
            else:
                coin_info = data
                
            tags = coin_info.get("tags", []) if isinstance(coin_info, dict) else []
            if tags:
                tag_names = [t if isinstance(t, str) else t.get("name", "") for t in tags[:5]]
                tag_names = [t for t in tag_names if t]
                if tag_names:
                    result.append(f"Tags: {', '.join(tag_names)}")
                    
        return " | ".join(result) if result else "No fundamental data found."
    except Exception as e:
        logger.error(f"Error fetching fundamentals for {clean_symbol}: {e}")
        return f"Exception fetching fundamentals: {e}"

def call_gemini_with_fallback(client, prompt, primary_model, fallback_model, max_retries=3, wait_time=600):
    """
    Tries primary_model. If it fails, waits wait_time seconds. 
    After max_retries, it switches to fallback_model.
    """
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling API (Model: {primary_model}, Attempt {attempt+1}/{max_retries})")
            response = client.models.generate_content(model=primary_model, contents=prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error on {primary_model}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            
    if fallback_model:
        logger.warning(f"All {max_retries} retries failed for {primary_model}. Falling back to {fallback_model}...")
        try:
            response = client.models.generate_content(model=fallback_model, contents=prompt)
            return response.text
        except Exception as e:
            logger.error(f"Fallback model {fallback_model} also failed: {e}")
            raise e
    else:
        raise Exception("Max retries reached and no fallback model provided.")

def generate_trade_insight_core(symbol: str, action: str, profit_pct: float, entry_price: float, exit_price: float, algorithm: str, algo_source: str = "", ohlc_data: str = ""):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise Exception("Missing GEMINI_API_KEY")
        
    client = genai.Client(api_key=api_key)
    
    news_context = fetch_crypto_news()
    macro_context = fetch_macro_context()
    fundamental_data = fetch_coin_fundamentals(symbol)
    
    prompt = f"""
    Act as a Senior Quantitative Analyst. 
    Our algorithmic trading bot ({algorithm}) just closed a position.
    
    Trade Details:
    - Coin: {symbol}
    - Action: {action} (Close Position)
    - Entry Price: ${entry_price:.4f}
    - Exit Price: ${exit_price:.4f}
    - Profit/Loss: {profit_pct:.2f}%
    
    Algorithm Source Code:
    ```python
    {algo_source}
    ```
    
    Recent OHLC Data (4h candles):
    {ohlc_data}
    
    Support Factors:
    - Global Macro Context: {macro_context}
    - Coin Fundamental Data: {fundamental_data}
    - Recent Crypto News Context: {news_context}
    
    Conduct a deep-dive analysis on this trade focusing primarily on the algorithm logic and coin price behavior.
    Address the following points in your analysis:
    - Why didn't the algorithm close the position at the highest price?
    - Was the entry point optimal enough?
    - How can we adjust our logic to achieve higher profit?
    - Are there any signs of anomalous price behavior?
    - Did the algorithm prematurely exit due to noise, or was it a solid risk-management decision?
    - What specific technical thresholds (e.g., RSI, MACD, MA) from the logic were triggered, and were they accurate?
    - Is the algorithm overly sensitive to volatility, or too slow to react during this trade?
    - Were there missed opportunities to scale in or scale out (take partial profits) during the trend?
    
    Provide your output in JSON format with exactly three keys:
    1. "summary": A detailed breakdown answering the questions above, connecting algorithm logic with price action behavior.
    2. "macro_context": Analyze how macro anomalies, fundamentals, or news explicitly influenced the asset's momentum as a support factor.
    3. "lessons_learned": A high-level statistical or logical insight that the Strategy Optimizer (AI 1.2) can use to identify systemic flaws or edge cases, explicitly suggesting logic adjustments.
    
    Output ONLY valid JSON. Provide a deep, insightful analysis in Thai language.
    """
    
    # AI 1.1 uses gemini-3.6-flash without fallback
    fast_model = os.getenv("GEMINI_MODEL_FAST", "gemini-3.6-flash")
    text = call_gemini_with_fallback(client, prompt, fast_model, None, max_retries=1, wait_time=0)
    
    if text.startswith("```json"):
        text = text[7:-3]
    elif text.startswith("```"):
        text = text[3:-3]
        
    result = json.loads(text.strip())
    return result

def async_generate_trade_insight_worker(trade_id: int, symbol: str, action: str, profit_pct: float, entry_price: float, exit_price: float, algorithm: str):
    """
    AI 1.1 Background Worker. Infinite retry every 10 mins until successful.
    """
    logger.info(f"AI 1.1 Worker started for trade_id {trade_id}")
    while True:
        try:


            
            db = SessionLocal()
            algo_source = ""
            ohlc_data = ""
            try:
                trade = db.query(Trade).filter(Trade.id == trade_id).first()
                limit = 30
                if trade and trade.portfolio:
                    if trade.portfolio.file_name:
                        algo_source = read_algo_source(trade.portfolio.file_name)
                        
                    # Find the corresponding BUY trade to calculate holding duration
                    buy_trade = db.query(Trade).filter(
                        Trade.portfolio_id == trade.portfolio_id,
                        Trade.symbol == trade.symbol,
                        Trade.action == "BUY",
                        Trade.timestamp < trade.timestamp
                    ).order_by(Trade.timestamp.desc()).first()
                    
                    if buy_trade:
                        duration = trade.timestamp - buy_trade.timestamp
                        duration_hours = duration.total_seconds() / 3600
                        # 4h candles = duration in hours / 4. Add 10 candles as buffer for context.
                        calculated_limit = int((duration_hours / 4) + 10)
                        # Cap at 1000 (Binance maximum per request) and min 30
                        limit = min(max(calculated_limit, 30), 1000)
                    
                df = fetch_klines(symbol, interval="4h", limit=limit)
                if df is not None and not df.empty:
                    ohlc_data = df.to_string()
            except Exception as e:
                logger.error(f"Error fetching extra context for AI 1.1: {e}")
            finally:
                db.close()
                
            insight_data = generate_trade_insight_core(symbol, action, profit_pct, entry_price, exit_price, algorithm, algo_source, ohlc_data)
            
            db = SessionLocal()
            try:
                insight = AIInsight(
                    trade_id=trade_id,
                    summary=insight_data.get("summary", ""),
                    macro_context=insight_data.get("macro_context", ""),
                    lessons_learned=insight_data.get("lessons_learned", "")
                )
                db.add(insight)
                db.commit()
                logger.info(f"AI 1.1: Successfully saved insight for trade {trade_id}")
            except Exception as e:
                logger.error(f"AI 1.1 DB Error: {e}")
                db.rollback()
            finally:
                db.close()
            break # Exit on success
            
        except Exception as e:
            logger.error(f"AI 1.1 API Error: {e}. Retrying in 10 minutes...")
            time.sleep(600)

def read_algo_source(file_name):
    try:
        path = os.path.join("algorithms", file_name)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading source for {file_name}: {e}")
        return ""

def async_weekly_optimizer_worker(portfolio_id: int):
    """
    AI 1.2 Background Worker. Retries 3 times then falls back to flash.
    """
    logger.info(f"AI 1.2 Worker started for portfolio_id {portfolio_id}")

    db = SessionLocal()
    
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
        if not portfolio: return
        
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        trades = db.query(Trade).filter(Trade.portfolio_id == portfolio_id, Trade.timestamp >= one_week_ago, Trade.action == "SELL").all()
        
        if not trades:
            logger.info(f"No trades this week for portfolio {portfolio_id} to optimize.")
            db_opt = DailyOptimizationResult(
                portfolio_id=portfolio_id,
                needs_tuning=0,
                analysis="No closed trades in the past week, standing by.",
                suggested_changes="N/A"
            )
            db.add(db_opt)
            db.commit()
            return
            
        trade_data_for_ai = []
        for t in trades:
            insight = db.query(AIInsight).filter(AIInsight.trade_id == t.id).first()
            trade_data_for_ai.append({
                "symbol": t.symbol,
                "profit_pct": f"{t.profit_pct:.2f}%" if t.profit_pct else "N/A",
                "insight_summary": insight.summary if insight else "No insight",
                "lessons_learned": insight.lessons_learned if insight else "No lesson"
            })
            
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key: return
        
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        Act as a Lead Strategy Optimizer (Portfolio Manager).
        Review these closed trades from the past week for algorithm: {portfolio.algorithm_name}.
        
        Trades Data:
        {trade_data_for_ai}
        
        Analyze the common patterns in these trades. Identify any consistent mistakes or market conditions the algorithm is struggling with.
        
        Provide your output in JSON format with exactly three keys:
        1. "needs_tuning": boolean (true if you strongly recommend adjusting the algorithm parameters, false if performance is acceptable).
        2. "analysis": A brief explanation of the patterns found this week.
        3. "suggested_changes": What parameters or logic should be changed (if any).
        
        Output ONLY valid JSON. Keep the tone professional in Thai language.
        """
        
        try:
            # AI 1.2: gemini-3.1-pro-preview with 3 retries (10 min apart), fallback to flash
            smart_model = os.getenv("GEMINI_MODEL_SMART", "gemini-3.1-pro-preview")
            fast_model = os.getenv("GEMINI_MODEL_FAST", "gemini-3.6-flash")
            text = call_gemini_with_fallback(client, prompt, smart_model, fast_model, max_retries=3, wait_time=600)
            
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
                
            result = json.loads(text.strip())
            
            needs_tuning = 1 if result.get("needs_tuning", False) else 0
            db_opt = DailyOptimizationResult(
                portfolio_id=portfolio_id,
                needs_tuning=needs_tuning,
                analysis=result.get("analysis", ""),
                suggested_changes=result.get("suggested_changes", "")
            )
            db.add(db_opt)
            db.commit()
            
            # Trigger AI 1.3
            ai_1_3_executor_core(db, portfolio, result)
            
        except Exception as e:
            logger.error(f"AI 1.2 totally failed: {e}")
            
    finally:
        db.close()

def ai_1_3_executor_core(db, portfolio, optimization_result: dict):
    """
    AI 1.3: Quant Developer & Backtester
    Called internally by AI 1.2 worker thread, uses same retry/fallback.
    """
    needs_tuning = optimization_result.get("needs_tuning", False)
    
    if needs_tuning and portfolio.file_name:
        logger.info(f"AI 1.3: Starting code generation & backtest for {portfolio.algorithm_name}...")
        
        old_source = read_algo_source(portfolio.file_name)
        if not old_source: return
        
        prompt = f"""
        You are an elite AI Quant Developer (AI 1.3).
        Your Portfolio Manager (AI 1.2) has analyzed recent trading data and requested the following changes to the current algorithm.
        
        Manager's Analysis: {optimization_result.get('analysis', '')}
        Manager's Requested Changes: {optimization_result.get('suggested_changes', '')}
        
        Current Algorithm Source Code:
        ```python
        {old_source}
        ```
        
        TASK:
        Modify the Python code to implement the requested changes.
        Maintain the exact function signature: `def get_target_allocations(data_dict, current_holdings=None, total_value=10000.0):`
        Return ONLY valid, executable Python code. Do NOT wrap it in markdown block like ```python ... ```, just pure python code.
        """
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key: return
        client = genai.Client(api_key=api_key)
        
        try:
            # AI 1.3: gemini-3.1-pro-preview with 3 retries (10 min apart), fallback to flash
            smart_model = os.getenv("GEMINI_MODEL_SMART", "gemini-3.1-pro-preview")
            fast_model = os.getenv("GEMINI_MODEL_FAST", "gemini-3.6-flash")
            new_code = call_gemini_with_fallback(client, prompt, smart_model, fast_model, max_retries=3, wait_time=600)
            
            if new_code.startswith("```python"):
                new_code = new_code[9:-3].strip()
            elif new_code.startswith("```"):
                new_code = new_code[3:-3].strip()
                
            timestamp = int(time.time())
            new_file_name = f"gen_algo_{timestamp}.py"
            new_algo_name = f"{portfolio.algorithm_name} (AI Tuned {timestamp})"
            
            new_path = os.path.join("algorithms", new_file_name)
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(new_code)
                
            logger.info(f"AI 1.3: Generated new algo file: {new_file_name}")
            


            
            module_name = f"algorithms.{new_file_name.replace('.py', '')}"
            algo_module = importlib.import_module(module_name)
            new_algo_func = algo_module.get_target_allocations
            
            logger.info(f"AI 1.3: Running 2-year backtest on {new_algo_name}...")
            final_balance = backtester.run_backtest(new_algo_func, initial_balance=10000.0, days=730)
            
            if final_balance >= 15000.0:

                logger.info(f"AI 1.3: SUCCESS! Backtest passed with ${final_balance:.2f}. Registering {new_algo_name}...")
                new_port = Portfolio(
                    algorithm_name=new_algo_name,
                    description=f"Auto-generated by AI 1.3 based on {portfolio.algorithm_name}. Expected 2Y ROI: {((final_balance-10000)/10000)*100:.2f}%",
                    balance_usd=10000.0,
                    file_name=new_file_name
                )
                db.add(new_port)
                db.commit()
            else:
                logger.info(f"AI 1.3: REJECTED. Backtest failed criteria (${final_balance:.2f} < $15000.0).")
                
        except Exception as e:
            logger.error(f"AI 1.3 Execution failed: {e}")
            traceback.print_exc()

def run_weekly_optimizer(portfolio_id: int):
    """
    Entry point to spawn the AI 1.2 worker thread.
    """
    threading.Thread(target=async_weekly_optimizer_worker, args=(portfolio_id,)).start()
