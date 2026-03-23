from __future__ import annotations
from typing import List

from pydantic import BaseModel


class SynonymEntry(BaseModel):
    id: int
    attribute: str
    raw_value: str
    canonical_value: str
    is_active: bool


class SynonymCreateRequest(BaseModel):
    attribute: str
    raw_value: str
    canonical_value: str


class SynonymUpdateRequest(BaseModel):
    raw_value: str | None = None
    canonical_value: str | None = None
    is_active: bool | None = None


class SynonymAttribute(BaseModel):
    name: str
    display_name: str


class SynonymAlias(BaseModel):
    id: int
    raw_value: str
    is_active: bool


class SynonymGroup(BaseModel):
    attribute: str
    attribute_display_name: str
    canonical_value: str
    synonyms: List[SynonymAlias]
