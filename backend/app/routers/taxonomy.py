from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from app.schemas_taxonomy import (
    TaxonomyNodeDetailOut,
    TaxonomyNodeOut,
    TaxonomySearchHitOut,
    TaxonomySearchOut,
    TaxonomyTopicOut,
)
from app.tender_taxonomy import (
    get_entry,
    get_node,
    search_taxonomy,
    taxonomy_flat_response,
    taxonomy_tree_json,
    taxonomy_tree_response,
)

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


def _node_out(node, *, include_children: bool = True) -> TaxonomyNodeOut:
    data = node.to_dict(include_children=include_children)
    return TaxonomyNodeOut(
        code=data["code"],
        title_fa=data["title_fa"],
        title_en=data["title_en"],
        kind=data.get("kind") or "category",
        items=list(data.get("items") or []),
        topics=[TaxonomyTopicOut(**t) for t in data.get("topics") or []],
        legacy_category=data["legacy_category"],
        subcategories=[_node_out(c, include_children=True) for c in node.subcategories]
        if include_children
        else [],
    )


@router.get("")
async def get_taxonomy_tree() -> Response:
    """Full taxonomy tree — pre-serialized JSON for fast, stable responses."""
    return Response(content=taxonomy_tree_json(), media_type="application/json; charset=utf-8")


@router.get("/flat")
async def get_taxonomy_flat() -> JSONResponse:
    return JSONResponse(content=taxonomy_flat_response())


@router.get("/search", response_model=TaxonomySearchOut)
async def search_taxonomy_endpoint(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> TaxonomySearchOut:
    hits = search_taxonomy(q, limit=limit)
    return TaxonomySearchOut(
        query=q,
        results=[TaxonomySearchHitOut(**h) for h in hits],
    )


@router.get("/{code}", response_model=TaxonomyNodeDetailOut)
async def get_taxonomy_node(code: str) -> TaxonomyNodeDetailOut:
    entry = get_entry(code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown taxonomy code: {code}")

    if entry.kind == "topic":
        parent = get_node(entry.parent_code or "")
        if parent is None:
            raise HTTPException(status_code=404, detail=f"Unknown taxonomy code: {code}")
        node = parent
    else:
        node = get_node(code)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Unknown taxonomy code: {code}")

    breadcrumbs: list[dict[str, str]] = []
    cursor = get_entry(node.code)
    while cursor is not None:
        breadcrumbs.insert(
            0,
            {"code": cursor.code, "title_fa": cursor.title_fa, "title_en": cursor.title_en},
        )
        cursor = get_entry(cursor.parent_code) if cursor.parent_code else None
    if entry.kind == "topic":
        breadcrumbs.append(
            {"code": entry.code, "title_fa": entry.title_fa, "title_en": entry.title_en},
        )

    return TaxonomyNodeDetailOut(node=_node_out(node), breadcrumbs=breadcrumbs)
