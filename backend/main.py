from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import traceback
from sqlalchemy.orm import Session
from typing import List

import database, schemas
from database import SessionLocal

def run_tick():
    import engine
    print("Scheduler running tick...")
    engine.tick_engine()

def run_optimization():
    import ai_agent
    from database import SessionLocal, Portfolio
    print("Scheduler running daily AI optimization...")
    db = SessionLocal()
    try:
        portfolios = db.query(Portfolio).all()
        for p in portfolios:
            ai_agent.run_daily_optimizer(db, p.id)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    from apscheduler.schedulers.background import BackgroundScheduler
    
    # Initialize default portfolios
    db = SessionLocal()
    try:
        algos = {
            "V4.0 Aggressive": "A momentum and volatility-based algorithm that aggressively enters top-performing assets during macro bull regimes, and liquidates entirely to USDT during bear regimes.",
            "V5.1 God Mode": "An advanced portfolio allocator that dynamically rebalances based on market sentiment and volume anomalies, aiming for steady growth with managed drawdowns."
        }
        for name, desc in algos.items():
            port = db.query(database.Portfolio).filter(database.Portfolio.algorithm_name == name).first()
            if not port:
                port = database.Portfolio(algorithm_name=name, balance_usd=10000.0, description=desc)
                db.add(port)
            elif port.description != desc:
                port.description = desc
        db.commit()
    except Exception as e:
        print(f"Error initializing portfolios: {e}")
    finally:
        db.close()

    scheduler = BackgroundScheduler()
    # Run every 4 hours
    scheduler.add_job(run_tick, 'interval', hours=4)
    # Run daily at 23:59
    scheduler.add_job(run_optimization, 'cron', hour=23, minute=59)
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

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/portfolios", response_model=List[schemas.PortfolioResponse])
def read_portfolios(db: Session = Depends(get_db)):
    portfolios = db.query(database.Portfolio).all()
    return portfolios

@app.get("/portfolios/{portfolio_id}", response_model=schemas.PortfolioResponse)
def read_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    portfolio = db.query(database.Portfolio).filter(database.Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio

@app.get("/trades/{portfolio_id}", response_model=List[schemas.TradeResponse])
def read_trades(portfolio_id: int, db: Session = Depends(get_db)):
    trades = db.query(database.Trade).filter(database.Trade.portfolio_id == portfolio_id).order_by(database.Trade.timestamp.desc()).limit(100).all()
    return trades

@app.post("/engine/tick")
def force_tick():
    import engine
    engine.tick_engine()
    return {"status": "success", "message": "Engine tick triggered"}

@app.post("/engine/optimize_now")
def force_optimize(db: Session = Depends(get_db)):
    import ai_agent
    portfolios = db.query(database.Portfolio).all()
    results = []
    for p in portfolios:
        res = ai_agent.run_daily_optimizer(db, p.id)
        results.append({"portfolio": p.algorithm_name, "optimization": res})
    return {"status": "success", "message": "Optimization triggered", "results": results}

@app.get("/market/prices")
def get_prices():
    from algorithms import data_fetcher
    prices = data_fetcher.get_live_prices(10)
    return {"status": "success", "data": prices}

@app.get("/api/ping")
def ping():
    return {"status": "alive", "message": "Pong! Server is awake."}

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
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
