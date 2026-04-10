from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recommendation import RecommendationResponse
from app.services.recommendation_service import get_recommendations

router = APIRouter()


@router.get("", response_model=RecommendationResponse)
def recommend(customer_code: str = Query(...), db: Session = Depends(get_db)):
    try:
        return get_recommendations(db, customer_code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
