import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager

# ==========================================
# 1. Pydantic Models for Input Validation
# ==========================================
class TradeRequest(BaseModel):
    symbol: str
    action: str  # "buy" หรือ "sell"
    volume: float # จำนวน Lot เช่น 0.01
    magic_number: int = 234000
    sl: float = 0.0 # Stop Loss (0 = ไม่ตั้ง)
    tp: float = 0.0 # Take Profit (0 = ไม่ตั้ง)
    comment: str = "API_Order"

# ==========================================
# 2. FastAPI Setup & MT5 Lifecycle
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # เชื่อมต่อ MT5 ตอนเปิด API
    if not mt5.initialize():
        print(f"MT5 initialize failed, error code: {mt5.last_error()}")
    else:
        print(f"✅ Connected to MT5. Version: {mt5.version()}")
    yield
    # ปิดการเชื่อมต่อตอนปิด API
    mt5.shutdown()
    print("❌ Disconnected from MT5")

app = FastAPI(title="MT5 Bridge API", lifespan=lifespan)

# ==========================================
# Secret Token Authentication Middleware
# ==========================================
import os
from dotenv import load_dotenv

load_dotenv()
API_SECRET_TOKEN = os.getenv("MT5_API_SECRET")

@app.middleware("http")
async def token_auth_middleware(request: Request, call_next):
    client_token = request.headers.get("Authorization")
    expected_token = f"Bearer {API_SECRET_TOKEN}"
    
    if client_token != expected_token:
        client_ip = request.client.host
        print(f"Blocked unauthorized access from IP: {client_ip} (Invalid Token)")
        return JSONResponse(
            status_code=401, 
            content={"detail": "Unauthorized: Invalid or missing API Token."}
        )
        
    return await call_next(request)

# ==========================================
# 3. API Endpoints
# ==========================================

@app.get("/")
def health_check():
    """เช็คสถานะการเชื่อมต่อ MT5"""
    info = mt5.terminal_info()
    if info is None:
        return {"status": "error", "message": "MT5 is not running or not connected"}
    return {"status": "ok", "connected": info.connected}

@app.get("/account")
def get_account_info():
    """ดึงข้อมูลบัญชี (Balance, Equity)"""
    account = mt5.account_info()
    if account is None:
        raise HTTPException(status_code=500, detail="Failed to get account info")
    return account._asdict()

@app.post("/trade")
def execute_trade(req: TradeRequest):
    """ส่งคำสั่งซื้อขาย (Buy/Sell)"""
    # 1. เช็คว่าเชื่อมต่อ MT5 หรือยัง
    if not mt5.terminal_info():
        mt5.initialize()

    # 2. เตรียมข้อมูล Symbol
    symbol = req.symbol
    if not mt5.symbol_select(symbol, True):
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in Market Watch")

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
         raise HTTPException(status_code=404, detail=f"Failed to get info for '{symbol}'")

    # 3. กำหนดฝั่งและราคา
    action_lower = req.action.lower()
    if action_lower not in ["buy", "sell"]:
        raise HTTPException(status_code=400, detail="Action must be 'buy' or 'sell'")

    order_type = mt5.ORDER_TYPE_BUY if action_lower == "buy" else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(symbol).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid

    # 4. สร้าง Request ส่งไป MT5
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": req.volume,
        "type": order_type,
        "price": price,
        "sl": req.sl,
        "tp": req.tp,
        "deviation": 20, # ยอมรับ Slippage 20 points
        "magic": req.magic_number,
        "comment": req.comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC, # เติมเท่าที่มี หรือ FOK
    }

    # 5. ส่งคำสั่ง
    result = mt5.order_send(request)
    
    # 6. เช็คผลลัพธ์
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {
            "success": False,
            "error_code": result.retcode,
            "message": result.comment
        }

    return {
        "success": True,
        "order_ticket": result.order,
        "price": result.price,
        "volume": result.volume
    }

@app.get("/history")
def get_history(symbol: str, timeframe: str = "4h", limit: int = 250):
    """ดึงประวัติราคา (Historical Klines)"""
    if not mt5.terminal_info():
        mt5.initialize()

    # Map string timeframe to MT5 timeframe constant
    tf_map = {
        "1m": mt5.TIMEFRAME_M1,
        "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
        "1w": mt5.TIMEFRAME_W1,
        "1mn": mt5.TIMEFRAME_MN1,
    }
    mt5_tf = tf_map.get(timeframe.lower(), mt5.TIMEFRAME_H4)
    
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, limit)
    if rates is None:
        raise HTTPException(status_code=404, detail=f"Rates not found for {symbol}")
        
    # Convert numpy array to list of dicts for JSON response
    result = []
    for r in rates:
        result.append({
            "time": int(r['time']),
            "open": float(r['open']),
            "high": float(r['high']),
            "low": float(r['low']),
            "close": float(r['close']),
            "tickVolume": float(r['tick_volume']),
            "realVolume": float(r['real_volume'])
        })
    return result

@app.get("/symbol")
def get_symbol_info(symbol: str):
    """ดึงข้อมูลสเปคของเหรียญ (เช่น เช็คว่าตลาดเปิดไหม)"""
    if not mt5.terminal_info():
        mt5.initialize()
        
    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
    return info._asdict()

if __name__ == "__main__":
    # รันเซิร์ฟเวอร์ที่ Port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
