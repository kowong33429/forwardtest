import os
import sys
from pydantic import ValidationError

# add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, Portfolio
from schemas import PortfolioResponse

def test():
    db = SessionLocal()
    try:
        portfolios = db.query(Portfolio).all()
        for p in portfolios:
            try:
                PortfolioResponse.from_orm(p)
            except ValidationError as e:
                print(f"Validation error for portfolio {p.id} ({p.algorithm_name}):")
                print(e)
    finally:
        db.close()

if __name__ == "__main__":
    test()
