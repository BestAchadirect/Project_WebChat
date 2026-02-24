import math
from typing import Tuple


def compute_total_pages(total_items: int, page_size: int) -> int:
    safe_total = max(0, int(total_items))
    safe_page_size = max(1, int(page_size))
    return max(1, math.ceil(safe_total / safe_page_size))


def clamp_page(page: int, total_pages: int) -> int:
    if total_pages <= 1:
        return 1
    return max(1, min(int(page), int(total_pages)))


def normalize_pagination(total_items: int, page: int, page_size: int) -> Tuple[int, int, int]:
    total_pages = compute_total_pages(total_items=total_items, page_size=page_size)
    safe_page = clamp_page(page=page, total_pages=total_pages)
    offset = (safe_page - 1) * max(1, int(page_size))
    return safe_page, total_pages, offset
