import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

# Load environment variables
load_dotenv()

# Use Cloud DB if provided, else fallback to local SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./forwardtest.db")

# check_same_thread is only for SQLite
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # PostgreSQL (Supabase/Neon) uses postgresql://, but sometimes sqlalchemy prefers postgresql+psycopg2://
    # We'll just use create_engine directly as SQLAlchemy handles standard postgresql:// fine in modern versions.
    # Note: If URL uses 'postgres://', SQLAlchemy 1.4+ requires 'postgresql://'
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True, index=True)
    algorithm_name = Column(String, unique=True, index=True) # e.g. "V4", "V5.1"
    description = Column(String, nullable=True) # Algorithm summary
    balance_usd = Column(Float, default=10000.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    trades = relationship("Trade", back_populates="portfolio")
    positions = relationship("Position", back_populates="portfolio")

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
    action = Column(String) # "BUY" or "SELL"
    amount = Column(Float)
    price = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    profit_pct = Column(Float, nullable=True) # Only for SELL
    
    portfolio = relationship("Portfolio", back_populates="trades")
    insight = relationship("AIInsight", back_populates="trade", uselist=False)

class AIInsight(Base):
    __tablename__ = "ai_insights"
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"))
    summary = Column(String)
    macro_context = Column(String)
    lessons_learned = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    trade = relationship("Trade", back_populates="insight")

class EngineLog(Base):
    __tablename__ = "engine_logs"
    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    logs_json = Column(String) # JSON string of calculation details

# Create tables
Base.metadata.create_all(bind=engine)
