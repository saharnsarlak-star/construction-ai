"""Apply additive Supabase migration. Does not print secrets."""
from __future__ import annotations

import asyncio
import pathlib
from urllib.parse import urlparse


def load_env(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


async def main() -> None:
    import asyncpg

    root = pathlib.Path(__file__).resolve().parents[2]
    env = load_env(root / "backend" / ".env")
    url = env.get("DATABASE_URL") or ""
    url = url.replace(":6543/", ":5432/")
    if "://" in url and "+" in url.split("://", 1)[0]:
        scheme, rest = url.split("://", 1)
        url = "postgresql://" + rest

    sql_path = root / "supabase" / "schema_additive_demo_auth_and_catalog.sql"
    raw = sql_path.read_text(encoding="utf-8")
    stmts = [s.strip() for s in raw.split(";") if s.strip() and not s.strip().startswith("--")]

    parsed = urlparse(url)
    print("connecting host=", parsed.hostname, "db=", (parsed.path or "/").lstrip("/"))
    conn = await asyncpg.connect(url, timeout=45, statement_cache_size=0)
    ok = 0
    try:
        for stmt in stmts:
            try:
                await conn.execute(stmt)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print("stmt_warn:", type(exc).__name__, str(exc)[:180])
        rows = await conn.fetch(
            """
            select table_name, column_name
            from information_schema.columns
            where table_schema='public'
              and (
                (table_name='catalog_standard_assets' and column_name in ('extracted_text','extraction_status'))
                or (table_name='app_users' and column_name in ('email','is_demo_user','demo_analyses_used'))
                or (table_name='findings' and column_name in ('source_excerpt','risk_score'))
              )
            order by table_name, column_name
            """
        )
        print("applied_ok", ok, "of", len(stmts))
        for r in rows:
            print("col", f"{r['table_name']}.{r['column_name']}")
    finally:
        await conn.close()
    print("SUPABASE_MIGRATION_DONE")


if __name__ == "__main__":
    asyncio.run(main())
