import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./forwardtest.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)
    
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True, index=True)
    algorithm_name = Column(String, unique=True, index=True) 
    description = Column(String, nullable=True) 
    balance_usd = Column(Float, default=10000.0)
    initial_balance = Column(Float, default=10000.0)
    is_hidden = Column(Integer, default=0) 
    is_ai_enabled = Column(Integer, default=1)
    is_deleted = Column(Integer, default=0)
    file_name = Column(String, nullable=True) 
    trading_type = Column(String, default="spot") # "spot" or "future"
    execution_type = Column(String, default="paper") # "paper" or "real"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    trades = relationship("Trade", back_populates="portfolio")
    positions = relationship("Position", back_populates="portfolio")
    futures_positions = relationship("FuturesPosition", back_populates="portfolio")
    futures_trades = relationship("FuturesTrade", back_populates="portfolio")

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String, index=True)
    amount = Column(Float, default=0.0)
    avg_entry_price = Column(Float, default=0.0)
    
    portfolio = relationship("Portfolio", back_populates="positions")

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String, index=True)
    action = Column(String) 
    amount = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    profit_pct = Column(Float, nullable=True) 
    reason = Column(String, nullable=True) 
    
    portfolio = relationship("Portfolio", back_populates="trades")
    insight = relationship("AIInsight", back_populates="trade", uselist=False)

class FuturesPosition(Base):
    __tablename__ = "futures_positions"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String, index=True)
    direction = Column(String) # LONG or SHORT
    amount = Column(Float, default=0.0)
    avg_entry_price = Column(Float, default=0.0)
    asset_class = Column(String, nullable=True) # crypto, forex, metal
    margin_type = Column(String, default="cross")
    liquidation_price = Column(Float, nullable=True)
    margin_used = Column(Float, default=0.0)
    accumulated_swap_or_funding = Column(Float, default=0.0)
    sl = Column(Float, nullable=True)
    tp = Column(Float, nullable=True)
    leverage = Column(Float, default=1.0)
    ticket_id = Column(String, nullable=True) # Exness MT5 ticket ID
    
    portfolio = relationship("Portfolio", back_populates="futures_positions")

class FuturesTrade(Base):
    __tablename__ = "futures_trades"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    symbol = Column(String, index=True)
    direction = Column(String) # LONG or SHORT
    action = Column(String) # OPEN or CLOSE
    amount = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    profit_pct = Column(Float, nullable=True) 
    profit_usd = Column(Float, nullable=True)
    asset_class = Column(String, nullable=True)
    margin_type = Column(String, nullable=True)
    commission = Column(Float, default=0.0)
    swap_or_funding = Column(Float, default=0.0)
    net_profit_usd = Column(Float, nullable=True)
    reason = Column(String, nullable=True) 
    ticket_id = Column(String, nullable=True)
    
    portfolio = relationship("Portfolio", back_populates="futures_trades")
    insight = relationship("FuturesAIInsight", back_populates="trade", uselist=False)

class AIInsight(Base):
    __tablename__ = "ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"))
    summary = Column(String)
    macro_context = Column(String)
    lessons_learned = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    trade = relationship("Trade", back_populates="insight")

class FuturesAIInsight(Base):
    __tablename__ = "futures_ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    futures_trade_id = Column(Integer, ForeignKey("futures_trades.id"))
    summary = Column(String)
    macro_context = Column(String)
    lessons_learned = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    trade = relationship("FuturesTrade", back_populates="insight")

class EngineLog(Base):
    __tablename__ = "engine_logs"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    logs_json = Column(String) 

class DailyOptimizationResult(Base):
    __tablename__ = "daily_optimization_results"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    needs_tuning = Column(Integer, default=0) 
    analysis = Column(String)
    suggested_changes = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)
