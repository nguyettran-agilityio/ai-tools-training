"""Tests for app.core.mappers.to_page — generic pagination helper, no DB."""

from app.core.mappers import to_page
from app.core.schemas import Page


class TestToPage:
    def test_empty_total_is_zero_pages(self):
        page: Page[int] = to_page(items=[], total=0, page=1, page_size=5, mapper_fn=lambda x: x)
        assert page.total_pages == 0
        assert page.items == []

    def test_total_pages_rounds_up(self):
        page = to_page(items=[1, 2, 3], total=11, page=1, page_size=5, mapper_fn=lambda x: x)
        assert page.total_pages == 3

    def test_applies_mapper_fn_to_each_item(self):
        page = to_page(items=[1, 2, 3], total=3, page=1, page_size=10, mapper_fn=lambda x: x * 2)
        assert page.items == [2, 4, 6]
