from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import traceback
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, inspect
from typing import List
import uvicorn

import database, schemas
from database import SessionLocal, Portfolio
import engine
from agents import ai_agent
from services import mt5_service
from algorithms import data_fetcher
from apscheduler.schedulers.background import BackgroundScheduler
from auth import auth_router, get_current_admin

def migrate_db(engine):
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('portfolios')]
        fp_columns = [col['name'] for col in inspector.get_columns('futures_positions')]
        ft_columns = [col['name'] for col in inspector.get_columns('futures_trades')]
        
        with engine.begin() as conn:
            if 'is_hidden' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN is_hidden INTEGER DEFAULT 0"))
            if 'is_ai_enabled' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN is_ai_enabled INTEGER DEFAULT 1"))
            if 'is_deleted' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN is_deleted INTEGER DEFAULT 0"))
            if 'file_name' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN file_name VARCHAR"))
            if 'trading_type' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN trading_type VARCHAR DEFAULT 'spot'"))
            if 'initial_balance' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN initial_balance FLOAT DEFAULT 10000.0"))
            if 'execution_type' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN execution_type VARCHAR DEFAULT 'paper'"))
            if 'algo_type' not in columns:
                conn.execute(text("ALTER TABLE portfolios ADD COLUMN algo_type VARCHAR DEFAULT 'crypto'"))
                
            # Migrate futures_positions
            if 'asset_class' not in fp_columns:
                conn.execute(text("ALTER TABLE futures_positions ADD COLUMN asset_class VARCHAR"))
            if 'margin_type' not in fp_columns:
                conn.execute(text("ALTER TABLE futures_positions ADD COLUMN margin_type VARCHAR DEFAULT 'cross'"))
            if 'liquidation_price' not in fp_columns:
                conn.execute(text("ALTER TABLE futures_positions ADD COLUMN liquidation_price FLOAT"))
            if 'margin_used' not in fp_columns:
                conn.execute(text("ALTER TABLE futures_positions ADD COLUMN margin_used FLOAT DEFAULT 0.0"))
            if 'accumulated_swap_or_funding' not in fp_columns:
                conn.execute(text("ALTER TABLE futures_positions ADD COLUMN accumulated_swap_or_funding FLOAT DEFAULT 0.0"))
                
            # Migrate futures_trades
            if 'asset_class' not in ft_columns:
                conn.execute(text("ALTER TABLE futures_trades ADD COLUMN asset_class VARCHAR"))
            if 'margin_type' not in ft_columns:
                conn.execute(text("ALTER TABLE futures_trades ADD COLUMN margin_type VARCHAR"))
            if 'commission' not in ft_columns:
                conn.execute(text("ALTER TABLE futures_trades ADD COLUMN commission FLOAT DEFAULT 0.0"))
            if 'swap_or_funding' not in ft_columns:
                conn.execute(text("ALTER TABLE futures_trades ADD COLUMN swap_or_funding FLOAT DEFAULT 0.0"))
            if 'net_profit_usd' not in ft_columns:
                conn.execute(text("ALTER TABLE futures_trades ADD COLUMN net_profit_usd FLOAT"))
    except Exception as e:
        print("Migration error:", e)

def run_tick(algo_name=None):

    print(f"Scheduler running tick for {algo_name if algo_name else 'ALL'}...")
    engine.tick_engine(algo_name)

def run_optimization():


    print("Scheduler running weekly AI optimization...")
    db = SessionLocal()
    try:
        portfolios = db.query(Portfolio).all()
        for p in portfolios:
            ai_agent.run_weekly_optimizer(db, p.id)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):

    
    # Initialize DB schema
    migrate_db(database.engine)
    
    # Initialize default portfolios
    db = SessionLocal()
    try:
        algos = {
            "V4.0 Aggressive": {"desc": "A momentum and volatility-based algorithm that aggressively enters top-performing assets during macro bull regimes, and liquidates entirely to USDT during bear regimes.", "file": "v4.py", "exec": "paper"},
            "V5.0 Low-Cap Sniper": {"desc": "Targets breakout Low-Cap gems (10M-300M Market Cap) on 4H candles with strict fundamental filters.", "file": "v5.py", "exec": "paper"},
            "V5.1 God Mode": {"desc": "An advanced portfolio allocator that dynamically rebalances based on market sentiment and volume anomalies, aiming for steady growth with managed drawdowns.", "file": "v5_1.py", "exec": "paper"},
            "V9 Kinetic God": {"desc": "Production Quantitative Scanner using Kinetic Energy Math, Calculus Deceleration, and dynamic Z-scores.", "file": "algo_v9_kinetic_god.py", "exec": "paper"},
            "V43 Whipsaw Killer": {"desc": "The ultimate Gold Future AI using HMM and Kalman Filter with CHOP indicator to avoid fractal consolidations. Supports Exness MT5 Cent account.", "file": "v43.py", "exec": "real"}
        }
        for name, data in algos.items():
            port = db.query(database.Portfolio).filter(database.Portfolio.algorithm_name == name).first()
            if not port:
                port = database.Portfolio(algorithm_name=name, balance_usd=10000.0, initial_balance=10000.0, description=data["desc"], file_name=data["file"], execution_type=data["exec"])
                db.add(port)
            else:
                port.description = data["desc"]
                if not port.file_name:
                    port.file_name = data["file"]
                if not getattr(port, 'execution_type', None):
                    port.execution_type = data["exec"]
        db.commit()
    except Exception as e:
        print(f"Error initializing portfolios: {e}")
    finally:
        db.close()

    scheduler = BackgroundScheduler()
    # Separate schedulers for each algorithm using precise 4H cron (UTC candle closures)
    scheduler.add_job(run_tick, 'cron', hour='0,4,8,12,16,20', minute=0, timezone='UTC', args=["V4.0 Aggressive"])
    scheduler.add_job(run_tick, 'cron', hour='0,4,8,12,16,20', minute=0, timezone='UTC', args=["V5.0 Low-Cap Sniper"])
    scheduler.add_job(run_tick, 'cron', hour='0,4,8,12,16,20', minute=0, timezone='UTC', args=["V5.1 God Mode"])
    scheduler.add_job(run_tick, 'cron', hour='0,4,8,12,16,20', minute=0, timezone='UTC', args=["V9 Kinetic God"])
    # Run daily at 17:00 New York Time (Market Close for Gold / Daily candle close)
    scheduler.add_job(run_tick, 'cron', hour=17, minute=0, timezone='America/New_York', args=["V43 Whipsaw Killer"])
    
    # Run weekly on Sunday at 23:59 USA Time (America/New_York)
    scheduler.add_job(run_optimization, 'cron', day_of_week='sun', hour=23, minute=59, timezone='America/New_York')
    scheduler.start()
    print("Background scheduler started.")
    yield
    scheduler.shutdown()
    print("Background scheduler shutdown.")

app = FastAPI(title="Forward Testing Platform API", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Error handling request {request.method} {request.url}")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error", "details": str(exc)},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/portfolios", response_model=List[schemas.PortfolioResponse])
def read_portfolios(db: Session = Depends(get_db)):
    portfolios = db.query(database.Portfolio).filter(database.Portfolio.is_deleted == 0).all()
    return portfolios

@app.get("/portfolios/{portfolio_id}", response_model=schemas.PortfolioResponse)
def read_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.query(database.Portfolio).filter(database.Portfolio.id == portfolio_id, database.Portfolio.is_deleted == 0).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio

@app.post("/portfolios/{portfolio_id}/toggle_hide")
def toggle_hide(portfolio_id: int, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    port = db.query(database.Portfolio).filter(database.Portfolio.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Not found")
    port.is_hidden = 1 if not port.is_hidden else 0
    db.commit()
    return {"status": "success", "is_hidden": bool(port.is_hidden)}

@app.post("/portfolios/{portfolio_id}/toggle_ai")
def toggle_ai(portfolio_id: int, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    port = db.query(database.Portfolio).filter(database.Portfolio.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Not found")
    port.is_ai_enabled = 1 if not port.is_ai_enabled else 0
    db.commit()
    return {"status": "success", "is_ai_enabled": bool(port.is_ai_enabled)}

@app.delete("/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    port = db.query(database.Portfolio).filter(database.Portfolio.id == portfolio_id).first()
    if not port:
        raise HTTPException(status_code=404, detail="Not found")
    port.is_deleted = 1
    db.commit()
    return {"status": "success", "message": "Portfolio deleted"}

@app.get("/trades/{portfolio_id}", response_model=schemas.PaginatedTradeResponse)
def read_trades(portfolio_id: int, page: int = 1, limit: int = 10, search: str = None, db: Session = Depends(get_db)):
    offset = (page - 1) * limit
    query = db.query(database.Trade).options(joinedload(database.Trade.insight)).filter(database.Trade.portfolio_id == portfolio_id)
    if search:
        query = query.filter(database.Trade.symbol.ilike(f"%{search}%"))
    
    total = query.count()
    trades = query.order_by(database.Trade.timestamp.desc()).offset(offset).limit(limit).all()
    total_pages = (total + limit - 1) // limit if limit > 0 else 1
    
    return {
        "data": trades,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }

@app.get("/futures_trades/{portfolio_id}", response_model=schemas.PaginatedFuturesTradeResponse)
def read_futures_trades(portfolio_id: int, page: int = 1, limit: int = 10, search: str = None, db: Session = Depends(get_db)):
    offset = (page - 1) * limit
    query = db.query(database.FuturesTrade).options(joinedload(database.FuturesTrade.insight)).filter(database.FuturesTrade.portfolio_id == portfolio_id)
    if search:
        query = query.filter(database.FuturesTrade.symbol.ilike(f"%{search}%"))
    
    total = query.count()
    trades = query.order_by(database.FuturesTrade.timestamp.desc()).offset(offset).limit(limit).all()
    total_pages = (total + limit - 1) // limit if limit > 0 else 1
    
    return {
        "data": trades,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


@app.post("/engine/tick")
def force_tick(admin: str = Depends(get_current_admin)):

    engine.tick_engine()
    return {"status": "success", "message": "Engine tick triggered"}

@app.post("/engine/optimize_now")
def force_optimize(db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):

    portfolios = db.query(database.Portfolio).all()
    for p in portfolios:
        ai_agent.run_weekly_optimizer(p.id)
    return {"status": "success", "message": "Optimization triggered in background for all portfolios"}

@app.get("/market/prices")
def get_prices(db: Session = Depends(get_db)):

    all_positions = db.query(database.Position).all()
    holding_symbols = list(set([p.symbol for p in all_positions]))
    prices = data_fetcher.get_live_prices(limit=30, additional_symbols=holding_symbols)
    return {"status": "success", "data": prices}

@app.get("/api/ping")
def ping():
    return {"status": "alive", "message": "Pong! Server is awake."}

@app.get("/api/mt5/health")
def mt5_health_check(admin: str = Depends(get_current_admin)):

    health = mt5_service.check_health()
    if health.get("status") == "error":
        print(f"Health Check Failed: {health.get('message')}")
        # Can also raise HTTPException, but returning JSON with error status is fine
        return JSONResponse(status_code=503, content=health)
    return health

@app.get("/engine_logs/{portfolio_id}", response_model=List[schemas.EngineLogResponse])
def get_engine_logs(portfolio_id: int, db: Session = Depends(get_db)):
    logs = db.query(database.EngineLog).filter(database.EngineLog.portfolio_id == portfolio_id).order_by(database.EngineLog.timestamp.desc()).limit(20).all()
    return logs

@app.get("/optimization/{portfolio_id}", response_model=List[schemas.DailyOptimizationResultResponse])
def get_optimization_results(portfolio_id: int, db: Session = Depends(get_db)):
    results = db.query(database.DailyOptimizationResult).filter(database.DailyOptimizationResult.portfolio_id == portfolio_id).order_by(database.DailyOptimizationResult.timestamp.desc()).limit(10).all()
    return results

# Entry point for running the server
if __name__ == "__main__":

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
