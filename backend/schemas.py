from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class AIInsightBase(BaseModel):
    summary: str
    macro_context: str
    lessons_learned: str

class AIInsightResponse(AIInsightBase):
    id: int
    trade_id: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class TradeBase(BaseModel):
    symbol: str
    action: str
    amount: float
    price: float
    profit_pct: Optional[float] = None
    reason: Optional[str] = None

class TradeResponse(TradeBase):
    id: int
    portfolio_id: int
    timestamp: datetime
    insight: Optional[AIInsightResponse] = None
    
    class Config:
        from_attributes = True

class FuturesTradeBase(BaseModel):
    symbol: str
    direction: str
    action: str
    amount: float
    price: float
    profit_pct: Optional[float] = None
    profit_usd: Optional[float] = None
    reason: Optional[str] = None
    ticket_id: Optional[str] = None

class FuturesTradeResponse(FuturesTradeBase):
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

class FuturesPositionResponse(BaseModel):
    id: int
    symbol: str
    direction: str
    amount: float
    avg_entry_price: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    leverage: float
    ticket_id: Optional[str] = None
    
    class Config:
        from_attributes = True

class PortfolioBase(BaseModel):
    algorithm_name: str
    description: Optional[str] = None
    balance_usd: float
    initial_balance: float = 10000.0
    is_hidden: bool = False
    is_ai_enabled: bool = True
    is_deleted: bool = False
    file_name: Optional[str] = None

class PortfolioResponse(PortfolioBase):
    id: int
    created_at: datetime
    updated_at: datetime
    positions: List[PositionResponse] = []
    futures_positions: List[FuturesPositionResponse] = []
    
    class Config:
        from_attributes = True

class EngineLogResponse(BaseModel):
    id: int
    portfolio_id: int
    timestamp: datetime
    logs_json: str
    
    class Config:
        from_attributes = True

class DailyOptimizationResultResponse(BaseModel):
    id: int
    portfolio_id: int
    needs_tuning: bool
    analysis: str
    suggested_changes: str
    timestamp: datetime
    
    class Config:
        from_attributes = True

class PaginatedTradeResponse(BaseModel):
    data: List[TradeResponse]
    total: int
    page: int
    limit: int
    total_pages: int

class PaginatedFuturesTradeResponse(BaseModel):
    data: List[FuturesTradeResponse]
    total: int
    page: int
    limit: int
    total_pages: int
