from typing import Any

from pydantic import BaseModel, Field


class TaxonomyTopicOut(BaseModel):
    code: str
    title_fa: str
    title_en: str
    parent_code: str
    kind: str = "topic"
    legacy_category: str


class TaxonomyNodeOut(BaseModel):
    code: str
    title_fa: str
    title_en: str
    kind: str = "category"
    items: list[str] = []
    topics: list[TaxonomyTopicOut] = []
    legacy_category: str
    subcategories: list["TaxonomyNodeOut"] = []


class TaxonomyMetaOut(BaseModel):
    schema_version: int = 1
    taxonomy_id: str = ""
    taxonomy_name: str
    language: str
    code_format: str = ""
    category_count: int
    subcategory_count: int = 0
    topic_count: int = 0
    total_codes: int = 0


class TaxonomyTreeOut(BaseModel):
    meta: TaxonomyMetaOut
    categories: list[TaxonomyNodeOut]


class TaxonomyFlatEntryOut(BaseModel):
    code: str
    title_fa: str
    title_en: str
    parent_code: str | None = None
    kind: str
    path_fa: str
    legacy_category: str


class TaxonomyFlatOut(BaseModel):
    meta: TaxonomyMetaOut
    entries: list[TaxonomyFlatEntryOut]


class TaxonomySearchHitOut(BaseModel):
    code: str
    title_fa: str
    title_en: str
    legacy_category: str
    parent_code: str | None = None
    kind: str | None = None
    path_fa: str | None = None


class TaxonomySearchOut(BaseModel):
    query: str
    results: list[TaxonomySearchHitOut]


class TaxonomyNodeDetailOut(BaseModel):
    node: TaxonomyNodeOut
    breadcrumbs: list[dict[str, str]] = Field(default_factory=list)


TaxonomyNodeOut.model_rebuild()
