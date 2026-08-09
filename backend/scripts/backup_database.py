"""Backup Supabase Postgres + local SQLite copies. Does not print secrets."""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
BACKUP_ROOT = ROOT.parent / "backups"


def _load_database_url() -> str:
    url = None
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                url = val.strip().strip('"').strip("'")
                break
    if not url:
        raise SystemExit("DATABASE_URL not found in backend/.env")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def _to_asyncpg_dsn(url: str) -> str:
    # Strip SQLAlchemy driver suffix if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    # asyncpg connect via DSN; ensure ssl for supabase
    dsn = url
    if "supabase.co" in (parsed.hostname or "") and "sslmode=" not in dsn and "ssl=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_hex__": bytes(value).hex()}
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


async def dump_supabase(out_dir: Path) -> dict:
    dsn = _to_asyncpg_dsn(_load_database_url())
    parsed = urlparse(dsn.split("?")[0])
    host = parsed.hostname or ""
    dbname = (parsed.path or "/").lstrip("/") or "postgres"

    conn = await asyncpg.connect(dsn)
    try:
        tables = await conn.fetch(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema', 'auth', 'storage', 'realtime', 'extensions', 'graphql', 'graphql_public', 'supabase_functions', 'vault', 'pgsodium', 'pgsodium_masks', 'net', 'cron')
            ORDER BY table_schema, table_name
            """
        )
        summary: dict = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "host": host,
            "database": dbname,
            "tables": {},
        }
        data_dir = out_dir / "tables"
        data_dir.mkdir(parents=True, exist_ok=True)

        for row in tables:
            schema, name = row["table_schema"], row["table_name"]
            fq = f'"{schema}"."{name}"'
            key = f"{schema}.{name}"
            try:
                cols = await conn.fetch(
                    """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = $1 AND table_name = $2
                    ORDER BY ordinal_position
                    """,
                    schema,
                    name,
                )
                records = await conn.fetch(f"SELECT * FROM {fq}")
                payload = {
                    "schema": schema,
                    "table": name,
                    "columns": [dict(c) for c in cols],
                    "row_count": len(records),
                    "rows": [{k: _jsonable(v) for k, v in dict(r).items()} for r in records],
                }
                out_file = data_dir / f"{schema}.{name}.json"
                out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                summary["tables"][key] = {"rows": len(records), "file": out_file.name}
                print(f"OK {key}: {len(records)} rows")
            except Exception as exc:  # noqa: BLE001
                summary["tables"][key] = {"error": str(exc)}
                print(f"FAIL {key}: {exc}")

        (out_dir / "manifest.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary
    finally:
        await conn.close()


def copy_local_sqlite(out_dir: Path) -> list[str]:
    sqlite_dir = out_dir / "sqlite_local"
    sqlite_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for db in ROOT.glob("*.db"):
        dest = sqlite_dir / db.name
        shutil.copy2(db, dest)
        copied.append(db.name)
        print(f"OK sqlite {db.name} ({db.stat().st_size} bytes)")
    return copied


def copy_schema_files(out_dir: Path) -> list[str]:
    schema_src = ROOT.parent / "supabase"
    schema_dst = out_dir / "schema_sql"
    schema_dst.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if schema_src.exists():
        for f in schema_src.glob("*.sql"):
            shutil.copy2(f, schema_dst / f.name)
            copied.append(f.name)
            print(f"OK schema {f.name}")
    return copied


def write_readme(out_dir: Path, summary: dict, sqlite_files: list[str], schema_files: list[str]) -> None:
    lines = [
        "# TenderRisk database backup",
        "",
        f"- Created (UTC): {summary.get('created_at')}",
        f"- Supabase host: {summary.get('host')}",
        f"- Database: {summary.get('database')}",
        "",
        "## Contents",
        "",
        "- `tables/*.json` — full row dumps of application tables from Supabase Postgres",
        "- `manifest.json` — table list and row counts",
        "- `sqlite_local/` — copies of local SQLite files used in development",
        "- `schema_sql/` — SQL schema files from the repo",
        "",
        "## Supabase tables",
        "",
    ]
    for name, meta in sorted((summary.get("tables") or {}).items()):
        if "rows" in meta:
            lines.append(f"- `{name}`: {meta['rows']} rows")
        else:
            lines.append(f"- `{name}`: ERROR — {meta.get('error')}")
    lines += [
        "",
        "## Local SQLite copies",
        "",
    ]
    for name in sqlite_files:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "## Schema SQL",
        "",
    ]
    for name in schema_files:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "## Restore notes",
        "",
        "1. Keep this folder offline (USB/Drive) — it contains your data.",
        "2. To recreate schema on a new Supabase project, run files in `schema_sql/` in order (start with `schema.sql`).",
        "3. To reload rows, import each `tables/*.json` into the matching table (or ask the agent to write a restore script).",
        "4. Local SQLite files can be used when running with `sqlite+aiosqlite` DATABASE_URL.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = BACKUP_ROOT / f"db_backup_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Backup folder: {out_dir}")

    summary = await dump_supabase(out_dir)
    sqlite_files = copy_local_sqlite(out_dir)
    schema_files = copy_schema_files(out_dir)
    write_readme(out_dir, summary, sqlite_files, schema_files)

    # Zip for easy copy
    zip_base = BACKUP_ROOT / f"db_backup_{stamp}"
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=out_dir)
    print(f"ZIP: {archive}")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
