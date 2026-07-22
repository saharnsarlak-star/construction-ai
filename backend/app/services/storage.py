from __future__ import annotations

import tempfile
from pathlib import Path

import httpx

from app.config import settings


class StorageError(RuntimeError):
    pass


def storage_mode() -> str:
    if settings.supabase_enabled:
        return "supabase"
    return "local"


async def save_upload(
    *,
    project_id: int,
    category: str,
    filename: str,
    data: bytes,
    content_type: str | None,
) -> tuple[str, Path]:
    """
    Persist file bytes.

    Returns (stored_path_reference, local_path_for_extraction).
    For Supabase mode, a temp local copy is also written so OCR can run.
    """
    safe_name = Path(filename).name or "unnamed"
    object_key = f"project_{project_id}/{category}/{safe_name}"

    if settings.supabase_enabled:
        await _supabase_upload(object_key, data, content_type)
        tmp = Path(tempfile.gettempdir()) / "tenderrisk" / object_key.replace("/", "_")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        return f"supabase://{settings.supabase_bucket}/{object_key}", tmp

    dest = settings.storage_dir / f"project_{project_id}" / category / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Avoid overwrite collisions
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while True:
            candidate = dest.with_name(f"{stem}_{i}{suffix}")
            if not candidate.exists():
                dest = candidate
                break
            i += 1
    dest.write_bytes(data)
    return str(dest), dest


async def open_for_read(stored_path: str) -> Path:
    """Return a local filesystem path for extraction/OCR."""
    if stored_path.startswith("supabase://"):
        # supabase://bucket/object/key...
        without = stored_path.removeprefix("supabase://")
        parts = without.split("/", 1)
        if len(parts) != 2:
            raise StorageError(f"Invalid supabase path: {stored_path}")
        bucket, object_key = parts
        data = await _supabase_download(bucket, object_key)
        tmp = Path(tempfile.gettempdir()) / "tenderrisk" / object_key.replace("/", "_")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        return tmp

    path = Path(stored_path)
    if not path.exists():
        raise StorageError(f"File missing: {stored_path}")
    return path


async def delete_stored(stored_path: str) -> None:
    if stored_path.startswith("supabase://"):
        without = stored_path.removeprefix("supabase://")
        parts = without.split("/", 1)
        if len(parts) != 2:
            return
        bucket, object_key = parts
        await _supabase_delete(bucket, object_key)
        return
    path = Path(stored_path)
    if path.exists():
        path.unlink()


async def _supabase_upload(object_key: str, data: bytes, content_type: str | None) -> None:
    url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{settings.supabase_bucket}/{object_key}"
    )
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key or "",
        "x-upsert": "true",
    }
    if content_type:
        headers["Content-Type"] = content_type
    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.post(url, content=data, headers=headers)
        if res.status_code >= 400:
            raise StorageError(f"Supabase upload failed: {res.status_code} {res.text}")


async def _supabase_download(bucket: str, object_key: str) -> bytes:
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key or "",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code >= 400:
            raise StorageError(f"Supabase download failed: {res.status_code} {res.text}")
        return res.content


async def _supabase_delete(bucket: str, object_key: str) -> None:
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key or "",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        await client.delete(url, headers=headers)
