from sqlalchemy.orm import Query


def paginate(query: Query, page: int = 1, page_size: int = 20) -> tuple[list, int]:
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total
