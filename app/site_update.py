from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import logging
import mimetypes
import posixpath
import queue
from pathlib import Path
import shutil
import threading
import time
from typing import Callable, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import storage
from pydantic import BaseModel

from app.auth import require_admin
from app.config import load_settings
from app.firestore import Site, get_client, get_collection, get_site, is_site_admin, list_admin_sites
from app.i18n import language_url, make_translator, request_language

settings = load_settings()
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger("uvicorn.error")

EMPTY_PUBLISHED_OBJECT_PATH = "__empty__"
DISPLAY_TIMEZONE = ZoneInfo("Asia/Tokyo")


def _template_context(request: Request, **values: object) -> dict:
    lang = request_language(request)
    return {
        "request": request,
        "lang": lang,
        "t": make_translator(lang),
        "language_url": lambda next_lang: language_url(request, next_lang),
        **values,
    }


class SignUploadRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class DeployRequest(BaseModel):
    object_path: str
    target: str = "staging"
    original_filename: str = ""


class PublishRequest(BaseModel):
    object_path: str
    target: str = "prod"


class PublishEmptyRequest(BaseModel):
    target: str = "prod"


class DeleteArchivesRequest(BaseModel):
    object_paths: list[str]


class ArchiveNoteRequest(BaseModel):
    note: str = ""


@dataclass(frozen=True)
class ZipEntry:
    name: str
    size: int
    crc32: int
    modified_at: str


@dataclass(frozen=True)
class ZipSummary:
    file_count: int
    total_size: int


@dataclass(frozen=True)
class CurrentPublicState:
    entries: dict[str, ZipEntry]
    object_names: set[str]
    verified: bool


ProgressCallback = Callable[[dict], None]
CancelCallback = Callable[[], bool]

operation_lock = threading.Lock()
operations: dict[str, dict] = {}
operation_subscribers: dict[str, list[queue.Queue[dict | None]]] = {}


class OperationCancelled(Exception):
    pass


class OperationReporter:
    def __init__(self, site_id: str, kind: str, object_path: str = ""):
        self.site_id = site_id
        self.kind = kind
        self.object_path = object_path
        self.operation_id = f"{kind}-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        self.last_write_at = 0.0

    def write(self, status: str, message: str, progress: int | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_write_at < 0.25:
            return
        self.last_write_at = now
        with operation_lock:
            existing = operations.get(self.site_id) or {}
            cancel_requested = bool(existing.get("cancel_requested")) if existing.get("operation_id") == self.operation_id else False
            data = {
                "operation_id": self.operation_id,
                "kind": self.kind,
                "object_path": self.object_path,
                "status": status,
                "message": message,
                "progress": progress,
                "cancel_requested": cancel_requested,
                "updated_at": datetime.utcnow(),
            }
            operations[self.site_id] = data

    def cancel_requested(self) -> bool:
        with operation_lock:
            operation = operations.get(self.site_id) or {}
            return bool(operation.get("cancel_requested"))


def _raise_if_cancelled(cancel_requested: CancelCallback | None) -> None:
    if cancel_requested and cancel_requested():
        raise OperationCancelled("処理を中止しました。")


def _cancel_operation(site_id: str) -> dict | None:
    with operation_lock:
        operation = operations.get(site_id)
        if not operation or operation.get("status") != "running":
            return None
        operation["cancel_requested"] = True
        operation["message"] = "停止します。"
        operation["updated_at"] = datetime.utcnow()
        return dict(operation)


def _subscribe_operation(site_id: str) -> queue.Queue[dict | None] | None:
    with operation_lock:
        operation = operations.get(site_id)
        if not operation or operation.get("status") != "running":
            return None
        subscriber: queue.Queue[dict | None] = queue.Queue()
        operation_subscribers.setdefault(site_id, []).append(subscriber)
        return subscriber


def _unsubscribe_operation(site_id: str, subscriber: queue.Queue[dict | None]) -> None:
    with operation_lock:
        subscribers = operation_subscribers.get(site_id)
        if not subscribers:
            return
        if subscriber in subscribers:
            subscribers.remove(subscriber)
        if not subscribers:
            operation_subscribers.pop(site_id, None)


def _publish_operation_event(site_id: str, event: dict) -> None:
    with operation_lock:
        subscribers = list(operation_subscribers.get(site_id) or [])
    for subscriber in subscribers:
        subscriber.put(dict(event))


def _close_operation_streams(site_id: str) -> None:
    with operation_lock:
        subscribers = operation_subscribers.pop(site_id, [])
    for subscriber in subscribers:
        subscriber.put(None)


def _current_operation(site_id: str) -> dict | None:
    with operation_lock:
        operation = operations.get(site_id)
        if not operation:
            return None
        if operation["status"] != "running" and (datetime.utcnow() - operation["updated_at"]).total_seconds() > 60:
            operations.pop(site_id, None)
            return None
        current = dict(operation)
        updated_at = current.get("updated_at")
        if isinstance(updated_at, datetime):
            current["updated_at"] = updated_at.isoformat() + "Z"
        return current


def _json_error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status_code)


def _format_display_datetime(value: datetime | None) -> str:
    if not value:
        return ""
    return value.astimezone(DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _require_history_bucket() -> None:
    if not settings.site_history_bucket:
        raise HTTPException(status_code=500, detail="SITE_HISTORY_BUCKET が未設定です。")


def _require_signed_url_settings() -> None:
    _require_history_bucket()
    if not settings.site_signed_url_service_account and not settings.gcp_project_id:
        raise HTTPException(status_code=500, detail="SITE_SIGNED_URL_SERVICE_ACCOUNT または GCP_PROJECT_ID が未設定です。")


def _history_prefix(site_id: str) -> str:
    return f"sites/{site_id}"


def _current_object_path(site_id: str) -> str:
    return f"{_history_prefix(site_id)}/current.zip"


def _archive_prefix(site_id: str) -> str:
    return f"{_history_prefix(site_id)}/archive/"


def _published_marker_path(site_id: str) -> str:
    return f"{_history_prefix(site_id)}/published.json"


def _archive_object_name(site_id: str, source_blob: storage.Blob) -> str:
    digest = hashlib.sha256()
    with source_blob.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{_archive_prefix(site_id)}{timestamp}-{digest.hexdigest()[:12]}.zip"


def _history_bucket(client: storage.Client) -> storage.Bucket:
    _require_history_bucket()
    return client.bucket(settings.site_history_bucket)


def _signed_url_service_account() -> str:
    if settings.site_signed_url_service_account:
        return settings.site_signed_url_service_account
    return f"webhost-app@{settings.gcp_project_id}.iam.gserviceaccount.com"


def _generate_upload_signed_url(blob: storage.Blob, content_type: str) -> str:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(GoogleAuthRequest())
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=10),
        method="PUT",
        content_type=content_type,
        service_account_email=_signed_url_service_account(),
        access_token=credentials.token,
    )


def _normalize_original_filename(value: str) -> str:
    name = Path(value).name.strip()
    if len(name) > 200:
        name = name[:200]
    return name


def _zip_modified_at(info: zipfile.ZipInfo) -> str:
    year, month, day, hour, minute, second = info.date_time
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def _zip_file_infos(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [info for info in zf.infolist() if not info.is_dir()]


def _validate_zip(zf: zipfile.ZipFile, site: Site) -> ZipSummary:
    infos = _zip_file_infos(zf)
    if not any(info.filename == "index.html" and not info.is_dir() for info in infos):
        raise HTTPException(status_code=400, detail="ZIP直下に index.html が必要です。")
    if len(infos) > site.upload_max_files:
        raise HTTPException(status_code=400, detail="ファイル数が上限を超えています。")
    total_size = 0
    for info in infos:
        total_size += info.file_size
        if info.file_size > site.upload_max_file_mb * 1024 * 1024:
            raise HTTPException(status_code=400, detail="ファイルサイズが上限を超えています。")
    if total_size > site.upload_max_total_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="総サイズが上限を超えています。")
    return ZipSummary(file_count=len(infos), total_size=total_size)


def _zip_manifest(zf: zipfile.ZipFile, site: Site) -> dict[str, ZipEntry]:
    _validate_zip(zf, site)
    manifest: dict[str, ZipEntry] = {}
    for info in _zip_file_infos(zf):
        manifest[info.filename] = ZipEntry(
            name=info.filename,
            size=info.file_size,
            crc32=info.CRC,
            modified_at=_zip_modified_at(info),
        )
    return manifest


def _is_public_object_path_supported(name: str) -> bool:
    return not name.startswith(".well-known/acme-challenge/")


def _public_zip_manifest(zf: zipfile.ZipFile, site: Site) -> dict[str, ZipEntry]:
    return {
        name: entry
        for name, entry in _zip_manifest(zf, site).items()
        if _is_public_object_path_supported(name)
    }


def _read_zip_manifest(source_blob: storage.Blob, site: Site) -> dict[str, ZipEntry]:
    with source_blob.open("rb") as stream:
        with zipfile.ZipFile(stream) as zf:
            return _zip_manifest(zf, site)


def _read_public_zip_manifest(source_blob: storage.Blob, site: Site) -> dict[str, ZipEntry]:
    with source_blob.open("rb") as stream:
        with zipfile.ZipFile(stream) as zf:
            return _public_zip_manifest(zf, site)


def _validate_zip_blob(source_blob: storage.Blob, site: Site) -> ZipSummary:
    with source_blob.open("rb") as stream:
        with zipfile.ZipFile(stream) as zf:
            return _validate_zip(zf, site)


def _empty_index_manifest() -> dict[str, ZipEntry]:
    return {"index.html": ZipEntry(name="index.html", size=0, crc32=0, modified_at="empty")}


def _same_zip_content(left: ZipEntry, right: ZipEntry) -> bool:
    return left.size == right.size and left.crc32 == right.crc32


def _set_zip_entry_metadata(blob: storage.Blob, entry: ZipEntry) -> None:
    blob.metadata = {
        "site_zip_crc32": f"{entry.crc32:08x}",
        "site_zip_size": str(entry.size),
        "site_zip_modified_at": entry.modified_at,
    }


def _content_type_for_public_object(name: str, site: Site) -> str:
    content_type, _ = mimetypes.guess_type(name)
    if site.html_charset and (name.endswith(".html") or name.endswith(".htm")):
        return f"text/html; charset={site.html_charset}"
    return content_type or "application/octet-stream"


def _should_refresh_public_object(name: str, site: Site) -> bool:
    return bool(site.html_charset and (name.endswith(".html") or name.endswith(".htm")))


def _published_marker_blob(bucket: storage.Bucket, site_id: str) -> storage.Blob:
    return bucket.blob(_published_marker_path(site_id))


def _load_published_object_path(bucket: storage.Bucket, site_id: str) -> str:
    marker = _published_marker_blob(bucket, site_id)
    try:
        if not marker.exists():
            return ""
        payload = json.loads(marker.download_as_text())
    except Exception as exc:
        logger.warning("公開履歴の読み込みに失敗しました: %s", exc)
        return ""
    return str(payload.get("object_path") or "")


def _save_published_marker(bucket: storage.Bucket, site_id: str, object_path: str) -> None:
    payload = {
        "object_path": object_path,
        "published_at": datetime.utcnow().isoformat() + "Z",
    }
    _published_marker_blob(bucket, site_id).upload_from_string(
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
    )


def _clear_published_marker(bucket: storage.Bucket, site: Site) -> None:
    marker = _published_marker_blob(bucket, site.site_id)
    try:
        if marker.exists():
            marker.delete()
    except Exception as exc:
        logger.warning("公開履歴マーカーの削除に失敗しました: %s", exc)
    _save_site_publish_state(site, "", None)


def _save_site_publish_state(site: Site, object_path: str, zip_created_at: datetime | None) -> None:
    db = get_client()
    data = {
        "published_object_path": object_path,
        "published_zip_created_at": zip_created_at,
        "updated_at": datetime.utcnow(),
    }
    get_collection(db, "sites").document(site.site_id).set(data, merge=True)


def _is_empty_published_object_path(object_path: str) -> bool:
    return object_path == EMPTY_PUBLISHED_OBJECT_PATH


def _validate_history_object_path(site_id: str, object_path: str, allow_current: bool = False) -> str:
    expected_archive_prefix = _archive_prefix(site_id)
    if allow_current and object_path == _current_object_path(site_id):
        return object_path
    if not object_path.startswith(expected_archive_prefix):
        raise HTTPException(status_code=400, detail="履歴ZIPのパスが不正です。")
    if posixpath.normpath(object_path) != object_path:
        raise HTTPException(status_code=400, detail="履歴ZIPのパスが不正です。")
    return object_path


def _archive_count(bucket: storage.Bucket, site_id: str) -> int:
    return sum(1 for blob in bucket.list_blobs(prefix=_archive_prefix(site_id)) if not blob.name.endswith("/"))


def _staging_root(site_id: str) -> Path:
    return (Path(settings.site_staging_dir) / site_id).resolve()


def _prepared_marker_path(site_id: str) -> Path:
    root = _staging_root(site_id)
    return root.parent / f"{root.name}.prepared"


def _clear_directory(path: Path, progress: ProgressCallback | None = None) -> int:
    count = 0
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return count
    for child in path.iterdir():
        if child.is_dir():
            count += sum(1 for item in child.rglob("*") if item.is_file())
            shutil.rmtree(child)
        else:
            child.unlink()
            count += 1
        if progress:
            progress({"stage": "clear", "deleted_count": count})
    return count


def _safe_staging_name(path: str) -> str:
    name = path.lstrip("/")
    if not name:
        return "index.html"
    if "\\" in name:
        raise HTTPException(status_code=404, detail="not found")
    if name.endswith("/"):
        name = f"{name}index.html"
    normalized = posixpath.normpath(name)
    if normalized != name or normalized.startswith("../") or normalized == "..":
        raise HTTPException(status_code=404, detail="not found")
    return normalized


def _deploy_zip_to_directory(source_blob: storage.Blob, site: Site, progress: ProgressCallback | None = None) -> dict:
    target_dir = _staging_root(site.site_id)
    deleted_count = _clear_directory(target_dir, progress=progress)
    uploaded_count = 0
    with source_blob.open("rb") as stream:
        with zipfile.ZipFile(stream) as zf:
            summary = _validate_zip(zf, site)
            infos = _zip_file_infos(zf)
            if progress:
                progress({"stage": "validated", "file_count": summary.file_count, "total_size": summary.total_size})
            for info in infos:
                try:
                    safe_name = _safe_staging_name(info.filename)
                except HTTPException as exc:
                    raise HTTPException(status_code=400, detail="stagingに展開できないパスが含まれています。") from exc
                target_path = (target_dir / safe_name).resolve()
                if not target_path.is_relative_to(target_dir):
                    raise HTTPException(status_code=400, detail="stagingに展開できないパスが含まれています。")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as file_handle:
                    with target_path.open("wb") as output:
                        shutil.copyfileobj(file_handle, output)
                uploaded_count += 1
                if progress:
                    progress({"stage": "extract", "uploaded_count": uploaded_count, "file_count": len(infos)})
    return {"deleted_count": deleted_count, "uploaded_count": uploaded_count}


def _mark_prepared_archive(site_id: str, object_path: str) -> None:
    marker = _prepared_marker_path(site_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(object_path, encoding="utf-8")


def _load_prepared_archive(site_id: str) -> str:
    marker = _prepared_marker_path(site_id)
    if not marker.is_file() or not (_staging_root(site_id) / "index.html").is_file():
        return ""
    object_path = marker.read_text(encoding="utf-8").strip()
    try:
        return _validate_history_object_path(site_id, object_path)
    except HTTPException:
        return ""


def _require_prepared_archive(site_id: str, object_path: str) -> None:
    prepared = _load_prepared_archive(site_id)
    if not prepared:
        raise HTTPException(status_code=409, detail="確認サイトが未準備です。先に確認サイトを用意してください。")
    if prepared != object_path:
        raise HTTPException(status_code=409, detail="別のZIPが確認サイトとして準備されています。公開前に確認サイトを用意してください。")


def _clear_prepared_if_matches(site_id: str, object_paths: Iterable[str]) -> None:
    marker = _prepared_marker_path(site_id)
    if not marker.is_file():
        return
    if marker.read_text(encoding="utf-8").strip() in set(object_paths):
        marker.unlink()


def _verify_bucket_matches_manifest(
    bucket: storage.Bucket,
    expected_entries: dict[str, ZipEntry],
    progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> None:
    blobs = {blob.name: blob for blob in bucket.list_blobs()}
    expected_names = set(expected_entries)
    actual_names = set(blobs)
    if actual_names != expected_names:
        raise HTTPException(status_code=409, detail="現公開ZIPと現公開内容のファイル一覧が一致しません。")
    checked_count = 0
    total_count = len(expected_entries)
    for name, expected in expected_entries.items():
        _raise_if_cancelled(cancel_requested)
        blob = blobs[name]
        if (blob.size or 0) != expected.size:
            raise HTTPException(status_code=409, detail=f"現公開内容のサイズが一致しません: {name}")
        metadata = blob.metadata or {}
        if metadata.get("site_zip_crc32") and metadata.get("site_zip_crc32") != f"{expected.crc32:08x}":
            raise HTTPException(status_code=409, detail=f"現公開内容のCRC32が一致しません: {name}")
        if metadata.get("site_zip_size") and metadata.get("site_zip_size") != str(expected.size):
            raise HTTPException(status_code=409, detail=f"現公開内容のメタデータサイズが一致しません: {name}")
        checked_count += 1
        if progress:
            progress({"stage": "verify", "checked_count": checked_count, "file_count": total_count})


def _public_object_names(bucket: storage.Bucket) -> set[str]:
    return {blob.name for blob in bucket.list_blobs() if not blob.name.endswith("/")}


def _load_current_public_state(history_bucket: storage.Bucket, public_bucket: storage.Bucket, site: Site) -> CurrentPublicState:
    published_object_path = _load_published_object_path(history_bucket, site.site_id)
    if _is_empty_published_object_path(published_object_path):
        entries = _empty_index_manifest()
        return CurrentPublicState(entries=entries, object_names=set(entries), verified=True)
    if not published_object_path:
        return CurrentPublicState(entries={}, object_names=_public_object_names(public_bucket), verified=False)
    try:
        _validate_history_object_path(site.site_id, published_object_path)
    except HTTPException:
        logger.warning("公開履歴マーカーが不正なため、本番内容を未確認として扱います: %s", published_object_path)
        return CurrentPublicState(entries={}, object_names=_public_object_names(public_bucket), verified=False)
    current_blob = history_bucket.blob(published_object_path)
    if not current_blob.exists():
        logger.warning("現公開ZIPが見つからないため、本番内容を未確認として扱います: %s", published_object_path)
        return CurrentPublicState(entries={}, object_names=_public_object_names(public_bucket), verified=False)
    try:
        entries = _read_public_zip_manifest(current_blob, site)
    except Exception as exc:
        logger.warning("現公開ZIPの読み込みに失敗したため、本番内容を未確認として扱います: %s", exc)
        return CurrentPublicState(entries={}, object_names=_public_object_names(public_bucket), verified=False)
    return CurrentPublicState(entries=entries, object_names=set(entries), verified=True)


def _delete_bucket_object_names(
    bucket: storage.Bucket,
    object_names: set[str],
    progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> int:
    deleted_count = 0
    for object_name in sorted(object_names):
        _raise_if_cancelled(cancel_requested)
        bucket.blob(object_name).delete()
        deleted_count += 1
        if progress:
            progress({"stage": "delete", "deleted_count": deleted_count})
    return deleted_count


def _deploy_zip_to_bucket(
    source_blob: storage.Blob,
    target_bucket: storage.Bucket,
    current_state: CurrentPublicState,
    site: Site,
    progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict:
    with source_blob.open("rb") as stream:
        with zipfile.ZipFile(stream) as zf:
            _raise_if_cancelled(cancel_requested)
            new_entries = _public_zip_manifest(zf, site)
            if progress:
                progress({"stage": "validated", "file_count": len(new_entries)})
            if current_state.verified:
                _verify_bucket_matches_manifest(
                    target_bucket,
                    current_state.entries,
                    progress=progress,
                    cancel_requested=cancel_requested,
                )
            changed_infos = []
            for info in _zip_file_infos(zf):
                _raise_if_cancelled(cancel_requested)
                if not _is_public_object_path_supported(info.filename):
                    continue
                current_entry = current_state.entries.get(info.filename)
                if current_entry and _same_zip_content(current_entry, new_entries[info.filename]) and not _should_refresh_public_object(info.filename, site):
                    continue
                changed_infos.append(info)
            removed_names = current_state.object_names - set(new_entries)
            if progress:
                progress(
                    {
                        "stage": "diff",
                        "changed_count": len(changed_infos),
                        "deleted_count": len(removed_names),
                        "skipped_count": len(new_entries) - len(changed_infos),
                        "file_count": len(new_entries),
                    }
                )
            copied_count = 0
            for info in changed_infos:
                _raise_if_cancelled(cancel_requested)
                entry = new_entries[info.filename]
                with zf.open(info) as file_handle:
                    target_blob = target_bucket.blob(info.filename)
                    target_blob.cache_control = "no-cache, max-age=0"
                    _set_zip_entry_metadata(target_blob, entry)
                    target_blob.upload_from_file(file_handle, content_type=_content_type_for_public_object(info.filename, site))
                    copied_count += 1
                    if progress:
                        progress({"stage": "upload", "copied_count": copied_count, "file_count": len(changed_infos)})
            deleted_count = _delete_bucket_object_names(target_bucket, removed_names, progress=progress, cancel_requested=cancel_requested)
    return {
        "deleted_count": deleted_count,
        "copied_count": copied_count,
        "skipped_count": len(new_entries) - copied_count,
    }


def _deploy_empty_index_to_bucket(
    target_bucket: storage.Bucket,
    progress: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict:
    deleted_count = 0
    blobs = list(target_bucket.list_blobs())
    total_count = len(blobs)
    for blob in blobs:
        _raise_if_cancelled(cancel_requested)
        blob.delete()
        deleted_count += 1
        if progress:
            progress({"stage": "delete", "deleted_count": deleted_count, "total_count": total_count})
    if progress:
        progress({"stage": "index", "deleted_count": deleted_count, "total_count": total_count})
    _raise_if_cancelled(cancel_requested)
    index_blob = target_bucket.blob("index.html")
    index_blob.cache_control = "no-cache, max-age=0"
    _set_zip_entry_metadata(index_blob, _empty_index_manifest()["index.html"])
    index_blob.upload_from_string("", content_type="text/html; charset=utf-8")
    return {"deleted_count": deleted_count, "copied_count": 1}


def _require_site_admin(request: Request, site_id: str) -> Site | RedirectResponse:
    auth = require_admin(request)
    if isinstance(auth, RedirectResponse):
        return auth
    db = get_client()
    site = get_site(db, site_id)
    if not site or not is_site_admin(db, site.site_id, str(auth.get("email") or "")):
        raise HTTPException(status_code=404, detail="サイトが見つかりません。")
    if not site.public_bucket:
        raise HTTPException(status_code=500, detail="公開用GCSバケットが未設定です。")
    return site


@router.get("/sites", response_class=HTMLResponse)
async def sites_index(request: Request):
    auth = require_admin(request)
    if isinstance(auth, RedirectResponse):
        return auth
    db = get_client()
    sites = list_admin_sites(db, str(auth.get("email") or ""))
    public_links = {
        site.site_id: bool(
            site.public_url
            and site.published_object_path
            and not _is_empty_published_object_path(site.published_object_path)
        )
        for site in sites
    }
    published_zip_dates = {
        site.site_id: _format_display_datetime(site.published_zip_created_at)
        for site in sites
        if public_links.get(site.site_id)
    }
    return templates.TemplateResponse(
        "sites.html",
        _template_context(
            request,
            title=make_translator(request_language(request))("sites.title"),
            sites=sites,
            public_links=public_links,
            published_zip_dates=published_zip_dates,
            admin_email=auth.get("email"),
            admin_picture=auth.get("picture"),
        ),
    )


@router.get("/sites/{site_id}", response_class=HTMLResponse)
async def site_detail(request: Request, site_id: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return site
    auth = require_admin(request)
    return templates.TemplateResponse(
        "site.html",
        _template_context(
            request,
            title=site.name,
            site=site,
            admin_email=auth.get("email") if isinstance(auth, dict) else None,
            admin_picture=auth.get("picture") if isinstance(auth, dict) else None,
        ),
    )


@router.post("/sites/{site_id}/api/sign-upload", response_class=JSONResponse)
async def sign_upload(request: Request, site_id: str, payload: SignUploadRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    _require_signed_url_settings()
    if payload.content_type not in {"application/zip", "application/x-zip-compressed"}:
        raise HTTPException(status_code=400, detail="content_type が不正です。")
    if payload.size_bytes <= 0:
        raise HTTPException(status_code=400, detail="size_bytes が不正です。")
    if payload.size_bytes > site.upload_max_total_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ZIPのサイズが上限を超えています。")

    client = storage.Client()
    bucket = _history_bucket(client)
    if _archive_count(bucket, site.site_id) >= site.archive_limit:
        raise HTTPException(status_code=400, detail="履歴数が上限に達しています。不要な履歴を削除してください。")
    object_path = _current_object_path(site.site_id)
    blob = bucket.blob(object_path)
    upload_url = _generate_upload_signed_url(blob, payload.content_type)
    return JSONResponse(
        {
            "upload_url": upload_url,
            "object_path": object_path,
            "expires_at": (datetime.utcnow() + timedelta(minutes=10)).isoformat() + "Z",
        }
    )


@router.post("/sites/{site_id}/api/deploy", response_class=JSONResponse)
async def deploy_site(request: Request, site_id: str, payload: DeployRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    if payload.target != "staging":
        raise HTTPException(status_code=400, detail="target は staging のみ指定できます。")
    _validate_history_object_path(site.site_id, payload.object_path, allow_current=True)

    client = storage.Client()
    bucket = _history_bucket(client)
    if _archive_count(bucket, site.site_id) >= site.archive_limit:
        raise HTTPException(status_code=400, detail="履歴数が上限に達しています。不要な履歴を削除してください。")
    source_blob = bucket.blob(payload.object_path)
    if not source_blob.exists():
        raise HTTPException(status_code=404, detail="ZIPが見つかりません。")
    summary = _validate_zip_blob(source_blob, site)
    archive_name = _archive_object_name(site.site_id, source_blob)
    archive_blob = bucket.copy_blob(source_blob, bucket, archive_name)
    metadata = dict(archive_blob.metadata or {})
    original_filename = _normalize_original_filename(payload.original_filename)
    if original_filename:
        metadata["original_filename"] = original_filename
    archive_blob.metadata = metadata
    archive_blob.patch()
    return JSONResponse(
        {
            "status": "ok",
            "target": "staging",
            "archive": archive_name,
            "file_count": summary.file_count,
            "total_size": summary.total_size,
        }
    )


@router.post("/sites/{site_id}/api/prepare-staging", response_class=JSONResponse)
async def prepare_staging(request: Request, site_id: str, payload: DeployRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    if payload.target != "staging":
        raise HTTPException(status_code=400, detail="target は staging のみ指定できます。")
    _validate_history_object_path(site.site_id, payload.object_path)

    client = storage.Client()
    bucket = _history_bucket(client)
    source_blob = bucket.blob(payload.object_path)
    if not source_blob.exists():
        raise HTTPException(status_code=404, detail="履歴ZIPが見つかりません。")

    def stream_prepare_progress():
        def emit(event: dict) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        progress_queue: queue.Queue[dict | None] = queue.Queue()
        operation = OperationReporter(site.site_id, "prepare-staging", payload.object_path)

        def enqueue_progress(event: dict) -> None:
            if event["stage"] == "validated":
                message = f"ZIPを確認しました。{event['file_count']}件を展開します。"
                progress_queue.put({"status": "progress", "stage": "validated", "message": message, "progress": 20})
                operation.write("running", message, 20)
            elif event["stage"] == "clear":
                message = f"確認サイトを空にしています。{event['deleted_count']}件"
                progress_queue.put({"status": "progress", "stage": "clear", "message": message, "progress": 10})
                operation.write("running", message, 10)
            elif event["stage"] == "extract":
                file_count = event["file_count"] or 1
                uploaded_count = event["uploaded_count"]
                message = f"確認サイトへ展開しています。{uploaded_count}/{file_count}件"
                progress_value = min(20 + round((uploaded_count / file_count) * 75), 95)
                progress_queue.put({"status": "progress", "stage": "extract", "message": message, "progress": progress_value})
                operation.write("running", message, progress_value)

        def run_prepare() -> None:
            try:
                result = _deploy_zip_to_directory(source_blob, site, progress=enqueue_progress)
                operation.write("running", "確認サイトを記録しています。", 98, force=True)
                progress_queue.put({"status": "progress", "stage": "marker", "message": "確認サイトを記録しています。", "progress": 98})
                _mark_prepared_archive(site.site_id, payload.object_path)
                operation.write("done", "確認サイトを用意しました。", 100, force=True)
                progress_queue.put({"status": "ok", "target": "staging", "object_path": payload.object_path, "progress": 100, **result})
            except Exception as exc:
                logger.exception("確認サイトの準備に失敗しました。")
                message = exc.detail if isinstance(exc, HTTPException) else "確認サイトの準備に失敗しました。"
                operation.write("error", message, None, force=True)
                progress_queue.put({"status": "error", "message": message})
            finally:
                progress_queue.put(None)

        operation.write("running", "確認サイトの準備を開始しています。", 0, force=True)
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()
        yield emit({"status": "progress", "stage": "start", "message": "確認サイトの準備を開始しています。", "progress": 0})
        while True:
            event = progress_queue.get()
            if event is None:
                break
            yield emit(event)

    return StreamingResponse(stream_prepare_progress(), media_type="application/x-ndjson")


@router.post("/sites/{site_id}/api/publish")
async def publish_site(request: Request, site_id: str, payload: PublishRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    if payload.target != "prod":
        raise HTTPException(status_code=400, detail="target は prod のみ指定できます。")
    _validate_history_object_path(site.site_id, payload.object_path)

    client = storage.Client()
    history_bucket = _history_bucket(client)
    public_bucket = client.bucket(site.public_bucket)
    source_blob = history_bucket.blob(payload.object_path)
    if not source_blob.exists():
        raise HTTPException(status_code=404, detail="履歴ZIPが見つかりません。")

    def stream_publish_progress():
        def emit(event: dict) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        progress_queue: queue.Queue[dict | None] = queue.Queue()
        operation = OperationReporter(site.site_id, "publish", payload.object_path)

        def publish_progress_event(event: dict) -> None:
            progress_queue.put(event)
            _publish_operation_event(site.site_id, event)

        def enqueue_progress(event: dict) -> None:
            if event["stage"] == "validated":
                message = f"ZIPを確認しました。{event['file_count']}件を公開します。"
                publish_progress_event({"status": "progress", "stage": "validated", "message": message, "progress": 10})
                operation.write("running", message, 10)
            elif event["stage"] == "verify":
                file_count = event["file_count"] or 1
                checked_count = event["checked_count"]
                message = f"現公開内容を確認しています。{checked_count}/{file_count}件"
                progress_value = min(10 + round((checked_count / file_count) * 10), 20)
                publish_progress_event({"status": "progress", "stage": "verify", "message": message, "progress": progress_value})
                operation.write("running", message, progress_value)
            elif event["stage"] == "diff":
                message = f"差分を確認しました。送信{event['changed_count']}件 / 削除{event['deleted_count']}件 / 変更なし{event['skipped_count']}件"
                publish_progress_event({"status": "progress", "stage": "diff", "message": message, "progress": 20})
                operation.write("running", message, 20, force=True)
            elif event["stage"] == "upload":
                file_count = event["file_count"] or 1
                copied_count = event["copied_count"]
                message = f"公開先へアップロードしています。{copied_count}/{file_count}件"
                progress_value = min(20 + round((copied_count / file_count) * 70), 90)
                publish_progress_event({"status": "progress", "stage": "upload", "message": message, "progress": progress_value})
                operation.write("running", message, progress_value)
            elif event["stage"] == "delete":
                message = f"不要な公開ファイルを削除しています。{event['deleted_count']}件"
                publish_progress_event({"status": "progress", "stage": "delete", "message": message, "progress": 95})
                operation.write("running", message, 95)

        def run_publish() -> None:
            try:
                _raise_if_cancelled(operation.cancel_requested)
                current_state = _load_current_public_state(history_bucket, public_bucket, site)
                _clear_published_marker(history_bucket, site)
                result = _deploy_zip_to_bucket(
                    source_blob,
                    public_bucket,
                    current_state,
                    site,
                    progress=enqueue_progress,
                    cancel_requested=operation.cancel_requested,
                )
                _raise_if_cancelled(operation.cancel_requested)
                operation.write("running", "公開履歴を記録しています。", 98, force=True)
                publish_progress_event({"status": "progress", "stage": "marker", "message": "公開履歴を記録しています。", "progress": 98})
                _save_published_marker(history_bucket, site.site_id, payload.object_path)
                source_blob.reload()
                metadata = dict(source_blob.metadata or {})
                metadata["last_published_at"] = datetime.utcnow().isoformat() + "Z"
                source_blob.metadata = metadata
                source_blob.patch()
                _save_site_publish_state(site, payload.object_path, source_blob.time_created)
                operation.write("done", "公開しました。", 100, force=True)
                publish_progress_event({"status": "ok", "target": "prod", "object_path": payload.object_path, "progress": 100, **result})
            except OperationCancelled as exc:
                message = str(exc)
                operation.write("cancelled", message, None, force=True)
                publish_progress_event({"status": "cancelled", "message": message})
            except Exception as exc:
                logger.exception("公開処理に失敗しました。")
                message = exc.detail if isinstance(exc, HTTPException) else "公開に失敗しました。"
                operation.write("error", message, None, force=True)
                publish_progress_event({"status": "error", "message": message})
            finally:
                _close_operation_streams(site.site_id)
                progress_queue.put(None)

        operation.write("running", "公開を開始しています。", 0, force=True)
        thread = threading.Thread(target=run_publish, daemon=True)
        thread.start()
        yield emit({"status": "progress", "stage": "start", "message": "公開を開始しています。", "progress": 0})
        while True:
            event = progress_queue.get()
            if event is None:
                break
            yield emit(event)

    return StreamingResponse(stream_publish_progress(), media_type="application/x-ndjson")


@router.post("/sites/{site_id}/api/publish-empty")
async def publish_empty(request: Request, site_id: str, payload: PublishEmptyRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    if payload.target != "prod":
        raise HTTPException(status_code=400, detail="target は prod のみ指定できます。")
    client = storage.Client()
    history_bucket = _history_bucket(client)
    public_bucket = client.bucket(site.public_bucket)

    def stream_empty_progress():
        def emit(event: dict) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        progress_queue: queue.Queue[dict | None] = queue.Queue()
        operation = OperationReporter(site.site_id, "publish-empty")

        def publish_progress_event(event: dict) -> None:
            progress_queue.put(event)
            _publish_operation_event(site.site_id, event)

        def enqueue_progress(event: dict) -> None:
            if event["stage"] == "delete":
                total_count = event["total_count"] or 1
                deleted_count = event["deleted_count"]
                message = f"公開ファイルを削除しています。{deleted_count}/{event['total_count']}件"
                progress_value = min(round((deleted_count / total_count) * 80), 80)
                publish_progress_event(
                    {
                        "status": "progress",
                        "stage": "delete",
                        "message": message,
                        "progress": progress_value,
                    }
                )
                operation.write("running", message, progress_value)
            elif event["stage"] == "index":
                message = "空のindex.htmlを設置しています。"
                publish_progress_event(
                    {
                        "status": "progress",
                        "stage": "index",
                        "message": message,
                        "progress": 90,
                    }
                )
                operation.write("running", message, 90, force=True)

        def run_publish_empty() -> None:
            try:
                _clear_published_marker(history_bucket, site)
                result = _deploy_empty_index_to_bucket(public_bucket, progress=enqueue_progress, cancel_requested=operation.cancel_requested)
                _raise_if_cancelled(operation.cancel_requested)
                operation.write("running", "公開履歴を記録しています。", 98, force=True)
                publish_progress_event({"status": "progress", "stage": "marker", "message": "公開履歴を記録しています。", "progress": 98})
                _save_published_marker(history_bucket, site.site_id, EMPTY_PUBLISHED_OBJECT_PATH)
                _save_site_publish_state(site, EMPTY_PUBLISHED_OBJECT_PATH, None)
                operation.write("done", "本番を空にしました。", 100, force=True)
                publish_progress_event({"status": "ok", "target": "prod", "object_path": "", "progress": 100, **result})
            except OperationCancelled as exc:
                message = str(exc)
                operation.write("cancelled", message, None, force=True)
                publish_progress_event({"status": "cancelled", "message": message})
            except Exception as exc:
                logger.exception("本番を空にする処理に失敗しました。")
                message = exc.detail if isinstance(exc, HTTPException) else "本番を空にできませんでした。"
                operation.write("error", message, None, force=True)
                publish_progress_event({"status": "error", "message": message})
            finally:
                _close_operation_streams(site.site_id)
                progress_queue.put(None)

        operation.write("running", "本番を空にする処理を開始しています。", 0, force=True)
        thread = threading.Thread(target=run_publish_empty, daemon=True)
        thread.start()
        yield emit({"status": "progress", "stage": "start", "message": "本番を空にする処理を開始しています。", "progress": 0})
        while True:
            event = progress_queue.get()
            if event is None:
                break
            yield emit(event)

    return StreamingResponse(stream_empty_progress(), media_type="application/x-ndjson")


@router.get("/sites/{site_id}/api/operation", response_class=JSONResponse)
async def get_operation(request: Request, site_id: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    return JSONResponse({"operation": _current_operation(site.site_id)})


@router.post("/sites/{site_id}/api/operation/stream")
async def stream_operation(request: Request, site_id: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)

    def stream_progress():
        def emit(event: dict) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        subscriber = _subscribe_operation(site.site_id)
        if subscriber is None:
            yield emit({"status": "idle"})
            return
        try:
            while True:
                event = subscriber.get()
                if event is None:
                    break
                yield emit(event)
        finally:
            _unsubscribe_operation(site.site_id, subscriber)

    return StreamingResponse(stream_progress(), media_type="application/x-ndjson")


@router.post("/sites/{site_id}/api/operation/cancel", response_class=JSONResponse)
async def cancel_operation(request: Request, site_id: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    operation = _cancel_operation(site.site_id)
    if not operation:
        return _json_error("実行中の処理はありません。", 409)
    _publish_operation_event(
        site.site_id,
        {
            "status": "progress",
            "stage": "cancel",
            "message": "停止します。",
            "progress": operation.get("progress"),
        },
    )
    return JSONResponse({"operation": _current_operation(site.site_id)})


@router.get("/sites/{site_id}/api/archives", response_class=JSONResponse)
async def list_archives(request: Request, site_id: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    client = storage.Client()
    bucket = _history_bucket(client)
    published_object_path = _load_published_object_path(bucket, site.site_id)
    prepared_object_path = _load_prepared_archive(site.site_id)
    archives = []
    for blob in bucket.list_blobs(prefix=_archive_prefix(site.site_id)):
        if blob.name.endswith("/"):
            continue
        metadata = blob.metadata or {}
        archives.append(
            {
                "object_path": blob.name,
                "filename": metadata.get("original_filename", ""),
                "created_at": blob.time_created.isoformat() if blob.time_created else "",
                "updated_at": blob.updated.isoformat() if blob.updated else "",
                "size_bytes": blob.size or 0,
                "note": metadata.get("note", ""),
                "is_published": blob.name == published_object_path,
                "last_published_at": metadata.get("last_published_at", ""),
            }
        )
    archives.sort(key=lambda item: item["created_at"], reverse=True)
    return JSONResponse(
        {
            "archives": archives,
            "archive_limit": site.archive_limit,
            "is_prod_empty": _is_empty_published_object_path(published_object_path),
            "prepared_object_path": prepared_object_path,
            "public_url": site.public_url,
            "staging_url": f"/sites/{site.site_id}/staging/",
            "operation": _current_operation(site.site_id),
        }
    )


@router.post("/sites/{site_id}/api/archives/delete", response_class=JSONResponse)
async def delete_archives(request: Request, site_id: str, payload: DeleteArchivesRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    object_paths = []
    for object_path in payload.object_paths:
        validated = _validate_history_object_path(site.site_id, object_path)
        if validated not in object_paths:
            object_paths.append(validated)
    if not object_paths:
        raise HTTPException(status_code=400, detail="削除する履歴を選択してください。")

    client = storage.Client()
    bucket = _history_bucket(client)
    published_object_path = _load_published_object_path(bucket, site.site_id)
    if published_object_path in object_paths:
        raise HTTPException(status_code=400, detail="公開中の履歴は削除できません。")
    deleted_count = 0
    for object_path in object_paths:
        blob = bucket.blob(object_path)
        if blob.exists():
            blob.delete()
            deleted_count += 1
    _clear_prepared_if_matches(site.site_id, object_paths)
    return JSONResponse({"status": "ok", "deleted_count": deleted_count})


@router.post("/sites/{site_id}/api/archives/{archive_name:path}/note", response_class=JSONResponse)
async def update_archive_note(request: Request, site_id: str, archive_name: str, payload: ArchiveNoteRequest):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return _json_error("unauthorized", 401)
    object_path = f"{_archive_prefix(site.site_id)}{archive_name}"
    _validate_history_object_path(site.site_id, object_path)
    note = payload.note.strip()
    if len(note) > 500:
        raise HTTPException(status_code=400, detail="メモは500文字以内で入力してください。")
    client = storage.Client()
    bucket = _history_bucket(client)
    blob = bucket.blob(object_path)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="履歴ZIPが見つかりません。")
    blob.reload()
    metadata = dict(blob.metadata or {})
    if note:
        metadata["note"] = note
    else:
        metadata.pop("note", None)
    blob.metadata = metadata
    blob.patch()
    return JSONResponse({"status": "ok", "object_path": object_path, "note": note})


@router.get("/sites/{site_id}/api/archives/{archive_name:path}/download")
async def download_archive(request: Request, site_id: str, archive_name: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return site
    object_path = f"{_archive_prefix(site.site_id)}{archive_name}"
    _validate_history_object_path(site.site_id, object_path)
    client = storage.Client()
    bucket = _history_bucket(client)
    blob = bucket.blob(object_path)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="履歴ZIPが見つかりません。")
    blob.reload()
    metadata = blob.metadata or {}
    filename = _normalize_original_filename(metadata.get("original_filename", "")) or Path(archive_name).name
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }

    def stream_blob():
        with blob.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                yield chunk

    return StreamingResponse(stream_blob(), media_type="application/zip", headers=headers)


@router.get("/sites/{site_id}/staging/{path:path}")
async def staging_site(request: Request, site_id: str, path: str):
    site = _require_site_admin(request, site_id)
    if isinstance(site, RedirectResponse):
        return site
    object_name = _safe_staging_name(path)
    staging_dir = _staging_root(site.site_id)
    if not (staging_dir / "index.html").is_file():
        raise HTTPException(status_code=404, detail="確認サイトが未準備です。管理画面で確認サイトを用意してください。")
    file_path = (staging_dir / object_name).resolve()
    if not file_path.is_relative_to(staging_dir) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type = _content_type_for_public_object(object_name, site)
    return FileResponse(file_path, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.get("/sites/{site_id}/staging")
async def staging_site_root(request: Request, site_id: str):
    return await staging_site(request, site_id, "")
