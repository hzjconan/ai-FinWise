from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session


def generate_code(db: Session, model, prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = f"{prefix}-{today}-%"
    count = db.query(func.count(model.id)).filter(model.code.like(pattern)).scalar()
    seq = count + 1
    return f"{prefix}-{today}-{seq:03d}"
