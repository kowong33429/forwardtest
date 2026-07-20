import os
from google import genai
import requests
import traceback
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIAgent")

def fetch_crypto_news():
    """
    Fetches recent news from CryptoPanic API (free, public).
    If it fails, returns a generic market context.
    """
    try:
        # CryptoPanic public endpoint for recent news
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
        traceback.print_exc()
        return f"Error fetching news: {e}"

def generate_trade_insight(symbol: str, action: str, profit_pct: float, entry_price: float, exit_price: float, algorithm: str):
    """
    Uses Gemini API to generate an insight like a Top Data Scientist.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "summary": "AI Agent offline (Missing GEMINI_API_KEY).",
            "macro_context": "N/A",
            "lessons_learned": "Provide API key in .env to enable AI insights."
        }
        
    client = genai.Client(api_key=api_key)
    
    news_context = fetch_crypto_news()
    
    prompt = f"""
    Act as a Senior Quantitative Analyst. 
    Our algorithmic trading bot ({algorithm}) just closed a position.
    
    Trade Details:
    - Coin: {symbol}
    - Action: {action} (Close Position)
    - Entry Price: ${entry_price:.4f}
    - Exit Price: ${exit_price:.4f}
    - Profit/Loss: {profit_pct:.2f}%
    
    Recent Crypto News Context: {news_context}
    
    Conduct a deep-dive analysis on this trade. Provide your output in JSON format with exactly three keys:
    1. "summary": A detailed breakdown of why this trade resulted in a profit/loss, connecting price action behavior with market conditions.
    2. "macro_context": Analyze how macro anomalies or news explicitly influenced the asset's momentum during the holding period.
    3. "lessons_learned": A high-level statistical or logical insight that the Strategy Optimizer (AI 1.2) can use to identify systemic flaws or edge cases.
    
    Output ONLY valid JSON. Provide a deep, insightful analysis in Thai language.
    """
    
    try:
        logger.info(f"Calling Gemini API (model: gemini-3.1-pro) for trade insight. Symbol: {symbol}, Action: {action}")
        logger.info(f"Prompt snippet: {prompt[:100]}...")
        
        response = client.models.generate_content(
            model='gemini-3.1-pro',
            contents=prompt,
        )
        
        logger.info(f"Gemini API call successful. Response length: {len(response.text)} chars.")
        # Parse JSON from response
        text = response.text
        # Clean markdown code block if present
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        import json
        result = json.loads(text.strip())
        logger.info(f"Successfully parsed Gemini JSON response.")
        return result
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        traceback.print_exc()
        return {
            "summary": f"Failed to generate insight: {e}",
            "macro_context": "Error parsing AI response.",
            "lessons_learned": "Ensure Gemini API is accessible."
        }

def send_telegram_notification(message: str):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("Telegram configuration missing. Skipping notification.")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        traceback.print_exc()
        print(f"Failed to send Telegram message: {e}")

def run_daily_optimizer(db, portfolio_id: int):
    """
    AI 1.2: Strategy Optimizer. Analyzes today's trades and insights.
    """
    from database import Trade, AIInsight, Portfolio
    from datetime import datetime, timedelta
    
    # Get portfolio name
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio: return None
    
    # Get last 24 hours trades
    yesterday = datetime.utcnow() - timedelta(days=1)
    trades = db.query(Trade).filter(Trade.portfolio_id == portfolio_id, Trade.timestamp >= yesterday, Trade.action == "SELL").all()
    
    if not trades:
        print(f"No trades today for portfolio {portfolio_id} to optimize.")
        return None
        
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
    if not api_key: return None
    
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    Act as a Lead Strategy Optimizer (Portfolio Manager).
    Review these closed trades from the past 24 hours for algorithm: {portfolio.algorithm_name}.
    
    Trades Data:
    {trade_data_for_ai}
    
    Analyze the common patterns in these trades. Identify any consistent mistakes or market conditions the algorithm is struggling with.
    
    Provide your output in JSON format with exactly three keys:
    1. "needs_tuning": boolean (true if you strongly recommend adjusting the algorithm parameters, false if performance is acceptable).
    2. "analysis": A brief explanation of the patterns found today.
    3. "suggested_changes": What parameters or logic should be changed (if any).
    
    Output ONLY valid JSON. Keep the tone professional in Thai language.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-3.1-pro',
            contents=prompt,
        )
        text = response.text
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        import json
        result = json.loads(text.strip())
        
        # Trigger AI 1.3
        ai_1_3_executor(portfolio.algorithm_name, result)
        return result
    except Exception as e:
        traceback.print_exc()
        print(f"AI 1.2 failed: {e}")
        return None

def ai_1_3_executor(algo_name: str, optimization_result: dict):
    """
    AI 1.3: Backtester & Notifier
    """
    needs_tuning = optimization_result.get("needs_tuning", False)
    
    if needs_tuning:
        # Simulate backtesting
        print(f"AI 1.3: Running backtest for {algo_name} based on AI 1.2 suggestions...")
        
        # Send Notification
        msg = f"🤖 *[AI 1.2 Alert]*\n"
        msg += f"*Algorithm:* {algo_name}\n"
        msg += f"*Analysis:* {optimization_result.get('analysis', '')}\n"
        msg += f"*Suggestion:* {optimization_result.get('suggested_changes', '')}\n\n"
        msg += "⏳ _AI 1.3 is simulating backtest for these changes..._"
        
        send_telegram_notification(msg)
