import os
import json
import logging
import time
from google import genai

logger = logging.getLogger("AIAgentStock")

def fetch_earnings_calendar():
    return "No major earnings this week for top indices."

def fetch_macro_context():
    return "S&P 500 near all-time highs, Fed signals potential rate cut later this year."

def fetch_stock_fundamentals(symbol: str):
    return f"{symbol} shows strong quarterly growth, but P/E ratio is above sector average."

def call_gemini_with_fallback(client, prompt, primary_model, fallback_model, max_retries=3, wait_time=600):

    for attempt in range(max_retries):
        try:
            logger.info(f"Calling API (Model: {primary_model}, Attempt {attempt+1}/{max_retries})")
            response = client.models.generate_content(model=primary_model, contents=prompt)
            return response.text
        except Exception as e:
            logger.error(f"Error on {primary_model}: {e}")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            
    if fallback_model:
        logger.warning(f"Falling back to {fallback_model}...")
        response = client.models.generate_content(model=fallback_model, contents=prompt)
        return response.text
    raise Exception("Max retries reached")

def generate_trade_insight_core(symbol: str, action: str, profit_pct: float, entry_price: float, exit_price: float, algorithm: str, algo_source: str = "", ohlc_data: str = ""):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise Exception("Missing GEMINI_API_KEY")
        
    client = genai.Client(api_key=api_key)
    
    earnings_context = fetch_earnings_calendar()
    macro_context = fetch_macro_context()
    fundamental_data = fetch_stock_fundamentals(symbol)
    
    prompt = f"""
    Act as a Senior Quantitative Equities Analyst. 
    Our algorithmic trading bot ({algorithm}) just closed a Stock position.
    
    Trade Details:
    - Stock: {symbol}
    - Action: {action} (Close Position)
    - Entry Price: {entry_price:.2f}
    - Exit Price: {exit_price:.2f}
    - Profit/Loss: {profit_pct:.2f}%
    
    Algorithm Source Code:
    ```python
    {algo_source}
    ```
    
    Recent OHLC Data (4h candles):
    {ohlc_data}
    
    Support Factors:
    - Macro Context: {macro_context}
    - Fundamental Data: {fundamental_data}
    - Earnings Calendar: {earnings_context}
    
    Conduct a deep-dive analysis on this trade focusing primarily on the algorithm logic and price action behavior.
    Address the following points in your analysis:
    - Why didn't the algorithm close the position at the highest price?
    - Was the entry point optimal enough?
    - How can we adjust our logic to achieve higher profit?
    - Are there any signs of anomalous price behavior?
    - Did the algorithm prematurely exit due to noise, or was it a solid risk-management decision?
    - What specific technical thresholds from the logic were triggered, and were they accurate?
    - Is the algorithm overly sensitive to volatility, or too slow to react during this trade?
    - Were there missed opportunities to scale in or scale out during the trend?
    
    Provide your output in JSON format with exactly three keys:
    1. "summary": A detailed breakdown answering the questions above, connecting algorithm logic with price action behavior.
    2. "macro_context": Analyze how macroeconomic events or earnings influenced the asset's momentum.
    3. "lessons_learned": A high-level statistical or logical insight explicitly suggesting logic adjustments.
    
    Output ONLY valid JSON. Provide a deep, insightful analysis in Thai language.
    """
    
    fast_model = os.getenv("GEMINI_MODEL_FAST", "gemini-3.6-flash")
    text = call_gemini_with_fallback(client, prompt, fast_model, None, max_retries=1, wait_time=0)
    
    if text.startswith("```json"):
        text = text[7:-3]
    elif text.startswith("```"):
        text = text[3:-3]
        
    result = json.loads(text.strip(), strict=False)
    return result
