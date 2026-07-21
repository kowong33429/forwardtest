from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class AIInsightBase(BaseModel):
    summary: str
    macro_context: str
    lessons_learned: str

class AIInsightResponse(AIInsightBase):
    id: int
    trade_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class TradeBase(BaseModel):
    symbol: str
    action: str
    amount: float
    price: float
    profit_pct: Optional[float] = None

class TradeResponse(TradeBase):
    id: int
    portfolio_id: int
    timestamp: datetime
    insight: Optional[AIInsightResponse] = None
    
    class Config:
        from_attributes = True

class PositionResponse(BaseModel):
    id: int
    symbol: str
    amount: float
    avg_entry_price: float
    
    class Config:
        from_attributes = True

class PortfolioBase(BaseModel):
    algorithm_name: str
    description: Optional[str] = None
    balance_usd: float

class PortfolioResponse(PortfolioBase):
    id: int
    created_at: datetime
    updated_at: datetime
    positions: List[PositionResponse] = []
    trades: List[TradeResponse] = []
    
    class Config:
        from_attributes = True

class EngineLogResponse(BaseModel):
    id: int
    portfolio_id: int
    timestamp: datetime
    logs_json: str
    
    class Config:
        from_attributes = True
