from collections.abc import AsyncGenerator
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

try:
    from app.dns_fallback import install_supabase_dns_fallback

    install_supabase_dns_fallback()
except Exception:  # noqa: BLE001 — optional DNS patch
    pass


class Base(DeclarativeBase):
    pass


def _postgres_url() -> str:
    url = settings.database_url
    if "postgresql" not in url:
        return url
    join = "&" if "?" in url else "?"
    if "prepared_statement_cache_size=" not in url:
        url = f"{url}{join}prepared_statement_cache_size=0"
    return url


def _base_asyncpg_connect_args() -> dict:
    return {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4().hex}__",
    }


def _build_engine(*, connect_args: dict | None = None) -> AsyncEngine:
    url = _postgres_url()
    is_postgres = "postgresql" in url
    if is_postgres:
        return create_async_engine(
            url,
            echo=False,
            poolclass=NullPool,
            connect_args=connect_args or _base_asyncpg_connect_args(),
        )
    return create_async_engine(url, echo=False)


engine = _build_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Import models so metadata is registered before create_all.
    from app import models  # noqa: F401
    from sqlalchemy import select, text

    from app.config import settings
    from app.db_connect import ensure_db_reachable
    from app.models import AppUser, UserRole

    try:
        await ensure_db_reachable(dns_attempts=12, connect_attempts=5)
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] db warmup warning: {exc}")

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] create_all warning: {exc}")

    # Ensure standards-catalog tables exist even if create_all was skipped earlier.
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS app_users (
                      id bigserial primary key,
                      username varchar(128) not null unique,
                      role varchar(16) not null default 'user',
                      api_token varchar(128) not null unique,
                      created_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_standard_assets (
                      id bigserial primary key,
                      standard_code varchar(64) not null unique,
                      title varchar(512) not null,
                      title_fa varchar(512),
                      title_en varchar(512),
                      title_de varchar(512),
                      publisher varchar(255),
                      standard_class varchar(32) not null default 'technical',
                      original_name varchar(512) not null,
                      stored_path varchar(1024) not null,
                      content_type varchar(255),
                      size_bytes integer not null default 0,
                      uploaded_by varchar(128),
                      created_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS project_standards (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      standard_code varchar(64) not null,
                      is_selected boolean not null default true,
                      selected_by varchar(32) not null default 'system_default',
                      applicability_level varchar(32),
                      standard_class varchar(32),
                      title varchar(512),
                      created_at timestamptz not null default now(),
                      unique (project_id, standard_code)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS experience_knowledge_items (
                      id bigserial primary key,
                      experience_id varchar(128) not null unique,
                      title varchar(512) not null,
                      description text not null default '',
                      category varchar(64) not null default 'lesson',
                      origin_kind varchar(64) not null default 'admin_curated',
                      source varchar(512),
                      author varchar(255),
                      validation_status varchar(64) not null default 'validated',
                      confidence_level varchar(32) not null default 'medium',
                      related_risk_id varchar(128),
                      related_risk_category varchar(64),
                      related_project_types_json text,
                      recommended_prevention text,
                      related_documents_json text,
                      related_outcomes_json text,
                      match_keywords_json text,
                      version integer not null default 1,
                      is_active boolean not null default true,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS registry_categories (
                      id bigserial primary key,
                      code varchar(64) not null unique,
                      title_fa varchar(255) not null,
                      title_en varchar(255),
                      description_fa text,
                      sort_order integer not null default 0,
                      color_index integer not null default 0,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_registry_categories_sort "
                    "ON registry_categories (sort_order)"
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS implementation_steps (
                      id bigserial primary key,
                      step_code varchar(64) not null unique,
                      phase varchar(32) not null,
                      sort_order integer not null default 0,
                      title_fa varchar(512) not null,
                      title_en varchar(512),
                      description_fa text,
                      description_en text,
                      status varchar(32) not null default 'pending',
                      category varchar(64) not null default 'general',
                      notes text,
                      metadata_json text,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_implementation_steps_sort "
                    "ON implementation_steps (sort_order)"
                )
            )
    except Exception as exc:  # noqa: BLE001
        # SQLite uses different DDL; create_all above already covers local DBs.
        print(f"[init_db] standards tables ensure warning: {exc}")

    # Phase B — ontology / knowledge graph tables (additive).
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS parties (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      legal_name varchar(512) not null,
                      party_role varchar(64) not null default 'unknown',
                      contact_ref varchar(512),
                      meta_json text,
                      created_at timestamptz not null default now(),
                      unique (project_id, legal_name, party_role)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS project_elements (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      element_type varchar(128) not null default 'element',
                      name_label varchar(512),
                      type_mark varchar(128),
                      ifc_global_id varchar(64),
                      match_key varchar(255) not null,
                      fire_rating varchar(64),
                      host_level varchar(128),
                      material_ref varchar(255),
                      drawing_ref varchar(128),
                      confidence integer,
                      meta_json text,
                      created_at timestamptz not null default now(),
                      updated_at timestamptz not null default now(),
                      unique (project_id, match_key)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS element_document_refs (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      element_id bigint not null references project_elements(id) on delete cascade,
                      document_id bigint not null references documents(id) on delete cascade,
                      source_kind varchar(64) not null,
                      source_local_id varchar(128) not null default '',
                      excerpt text,
                      confidence integer,
                      created_at timestamptz not null default now(),
                      unique (element_id, document_id, source_kind, source_local_id)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ontology_edges (
                      id bigserial primary key,
                      project_id bigint not null references projects(id) on delete cascade,
                      from_type varchar(64) not null,
                      from_id varchar(128) not null,
                      to_type varchar(64) not null,
                      to_id varchar(128) not null,
                      predicate varchar(64) not null,
                      confidence integer,
                      origin_kind varchar(32) not null default 'python',
                      document_id bigint references documents(id) on delete set null,
                      evidence_json text,
                      created_at timestamptz not null default now()
                    )
                    """
                )
            )
            try:
                await conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_standard_clauses_standard_clause "
                        "ON standard_clauses (standard_id, clause_number)"
                    )
                )
            except Exception:
                pass
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_edge_tuple "
                    "ON ontology_edges (project_id, from_type, from_id, to_type, to_id, predicate)"
                )
            )
            for idx_sql in (
                "CREATE INDEX IF NOT EXISTS idx_parties_project ON parties (project_id)",
                "CREATE INDEX IF NOT EXISTS idx_project_elements_project ON project_elements (project_id)",
                "CREATE INDEX IF NOT EXISTS idx_project_elements_ifc ON project_elements (ifc_global_id)",
                "CREATE INDEX IF NOT EXISTS idx_element_doc_refs_project ON element_document_refs (project_id)",
                "CREATE INDEX IF NOT EXISTS idx_element_doc_refs_element ON element_document_refs (element_id)",
                "CREATE INDEX IF NOT EXISTS idx_ontology_edges_project ON ontology_edges (project_id)",
                "CREATE INDEX IF NOT EXISTS idx_ontology_edges_predicate ON ontology_edges (predicate)",
                "CREATE INDEX IF NOT EXISTS idx_ontology_edges_from ON ontology_edges (from_type, from_id)",
                "CREATE INDEX IF NOT EXISTS idx_ontology_edges_to ON ontology_edges (to_type, to_id)",
            ):
                try:
                    await conn.execute(text(idx_sql))
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] ontology tables ensure warning: {exc}")

    # Additive columns for existing MVP Postgres databases (must not block boot).
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE projects "
                    "ADD COLUMN IF NOT EXISTS project_type VARCHAR(64) DEFAULT 'infrastructure'"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE projects "
                    "ADD COLUMN IF NOT EXISTS country_profile_code VARCHAR(64)"
                )
            )
            await conn.execute(
                text(
                    "UPDATE projects SET project_type = 'infrastructure' "
                    "WHERE project_type IS NULL"
                )
            )
            for stmt in (
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'approved'",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS company VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS phone VARCHAR(64)",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS message TEXT",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_project_id INTEGER",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_demo_user BOOLEAN DEFAULT FALSE",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_expires_at TIMESTAMPTZ",
                "ALTER TABLE app_users ADD COLUMN IF NOT EXISTS demo_analyses_used INTEGER DEFAULT 0",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_user_id INTEGER",
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT FALSE",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS finding_category VARCHAR(32) DEFAULT 'risk'",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS risk_score INTEGER",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_excerpt TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_document_name VARCHAR(512)",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_page INTEGER",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS cause_effect_json TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS data_completeness_caveat TEXT",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS estimated_impact VARCHAR(512)",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_layer VARCHAR(32)",
                "ALTER TABLE findings ADD COLUMN IF NOT EXISTS confidence_score INTEGER",
                "ALTER TABLE experience_knowledge_items ADD COLUMN IF NOT EXISTS match_keywords_json TEXT",
                "ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS extracted_text TEXT",
                "ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS extraction_status VARCHAR(32)",
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS taxonomy_code VARCHAR(32)",
                "ALTER TABLE catalog_standard_assets ADD COLUMN IF NOT EXISTS family_code VARCHAR(32)",
                "ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS section_title VARCHAR(512)",
                "ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS slot_code VARCHAR(160)",
                "ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS taxonomy_code VARCHAR(32)",
                "ALTER TABLE standard_clauses ADD COLUMN IF NOT EXISTS taxonomy_confidence DOUBLE PRECISION",
                "ALTER TABLE implementation_steps ADD COLUMN IF NOT EXISTS deliverables_fa TEXT",
                "ALTER TABLE implementation_steps ADD COLUMN IF NOT EXISTS related_paths TEXT",
                "ALTER TABLE implementation_steps ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE",
            ):
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    pass
            try:
                await conn.execute(
                    text("UPDATE app_users SET status = 'approved' WHERE status IS NULL OR status = ''")
                )
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] alter warning: {exc}")

    # SQLite / local DB: ensure app_users auth columns exist.
    try:
        async with engine.begin() as conn:
            for stmt in (
                "ALTER TABLE app_users ADD COLUMN email VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN password_hash VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN status VARCHAR(32) DEFAULT 'approved'",
                "ALTER TABLE app_users ADD COLUMN full_name VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN company VARCHAR(255)",
                "ALTER TABLE app_users ADD COLUMN phone VARCHAR(64)",
                "ALTER TABLE app_users ADD COLUMN message TEXT",
                "ALTER TABLE app_users ADD COLUMN demo_project_id INTEGER",
                "ALTER TABLE app_users ADD COLUMN is_demo_user BOOLEAN DEFAULT 0",
                "ALTER TABLE app_users ADD COLUMN demo_expires_at DATETIME",
                "ALTER TABLE app_users ADD COLUMN demo_analyses_used INTEGER DEFAULT 0",
                "ALTER TABLE projects ADD COLUMN owner_user_id INTEGER",
                "ALTER TABLE projects ADD COLUMN is_demo BOOLEAN DEFAULT 0",
                "ALTER TABLE findings ADD COLUMN source_document_name VARCHAR(512)",
                "ALTER TABLE findings ADD COLUMN source_page INTEGER",
                "ALTER TABLE catalog_standard_assets ADD COLUMN extracted_text TEXT",
                "ALTER TABLE catalog_standard_assets ADD COLUMN extraction_status VARCHAR(32)",
                "ALTER TABLE documents ADD COLUMN taxonomy_code VARCHAR(32)",
                "ALTER TABLE catalog_standard_assets ADD COLUMN family_code VARCHAR(32)",
                "ALTER TABLE standard_clauses ADD COLUMN section_title VARCHAR(512)",
                "ALTER TABLE standard_clauses ADD COLUMN slot_code VARCHAR(160)",
                "ALTER TABLE standard_clauses ADD COLUMN taxonomy_code VARCHAR(32)",
                "ALTER TABLE standard_clauses ADD COLUMN taxonomy_confidence FLOAT",
            ):
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    pass
            try:
                await conn.execute(text("UPDATE app_users SET status = 'approved' WHERE status IS NULL OR status = ''"))
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] app_users alter warning: {exc}")

    # Seed minimal admin/user principals for Phase 0 standards access control.
    try:
        from app.services.passwords import hash_password

        async with SessionLocal() as session:
            for username, role, token, email, password in (
                ("admin", UserRole.ADMIN, settings.admin_api_token, settings.admin_email, settings.admin_password),
                ("user", UserRole.USER, settings.user_api_token, settings.user_email, settings.user_password),
            ):
                existing = (
                    await session.execute(select(AppUser).where(AppUser.username == username))
                ).scalar_one_or_none()
                pwd_hash = hash_password(password)
                if existing is None:
                    session.add(
                        AppUser(
                            username=username,
                            email=email.strip().lower(),
                            password_hash=pwd_hash,
                            role=role,
                            api_token=token,
                        )
                    )
                else:
                    existing.role = role
                    existing.api_token = token
                    existing.email = email.strip().lower()
                    existing.password_hash = pwd_hash
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] app_users seed warning: {exc}")

    # Phase 6 — seed Risk Knowledge Base (46 Risk IDs from Batches 1–2). Additive upsert.
    try:
        from app.knowledge.rkb import seed_risks_table

        async with SessionLocal() as session:
            stats = await seed_risks_table(session)
            print(
                f"[init_db] RKB seed: inserted={stats['inserted']} "
                f"table_count={stats['table_count']} unique_seed={stats['unique_seed_ids']}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] risks seed warning: {exc}")

    try:
        from app.services.project_registry import seed_project_registry

        async with SessionLocal() as session:
            stats = await seed_project_registry(session)
            cats = stats["categories"]
            items = stats["items"]
            print(
                f"[init_db] project_registry seed: categories_inserted={cats['inserted']} "
                f"categories_updated={cats['updated']} items_inserted={items['inserted']} "
                f"items_backfilled={items['backfilled']} total_items={items['table_count']}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[init_db] project_registry seed warning: {exc}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
