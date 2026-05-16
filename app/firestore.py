from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from google.cloud import firestore

from app.config import load_settings

settings = load_settings()
SITE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


@dataclass(frozen=True)
class Site:
    site_id: str
    name: str
    public_bucket: str
    public_prefix: str
    public_url: str
    published_object_path: str
    published_zip_created_at: datetime | None
    html_charset: str
    enabled: bool
    archive_limit: int
    upload_max_total_mb: int
    upload_max_files: int
    upload_max_file_mb: int


def _normalize_prefix(prefix: str) -> str:
    trimmed = prefix.strip().strip("/")
    if not trimmed:
        return ""
    parts = trimmed.split("/")
    if len(parts) % 2 == 1:
        parts.append("current")
    return "/".join(parts)


def get_client() -> firestore.Client:
    return firestore.Client()


def get_collection(db: firestore.Client, name: str) -> firestore.CollectionReference:
    prefix = _normalize_prefix(settings.firestore_prefix)
    if not prefix:
        return db.collection(name)
    return db.document(prefix).collection(name)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_site_id(site_id: str) -> str:
    if not SITE_ID_PATTERN.fullmatch(site_id):
        raise ValueError("site_id が不正です。")
    return site_id


def _int_or_default(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None


def _normalize_public_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    return f"{url.rstrip('/')}/"


def _normalize_public_prefix(value: object) -> str:
    prefix = str(value or "").strip().strip("/")
    if not prefix:
        return ""
    return f"{prefix}/"


def site_from_doc(doc: firestore.DocumentSnapshot) -> Site:
    data = doc.to_dict() or {}
    return Site(
        site_id=doc.id,
        name=str(data.get("name") or doc.id),
        public_bucket=str(data.get("public_bucket") or ""),
        public_prefix=_normalize_public_prefix(data.get("public_prefix")),
        public_url=_normalize_public_url(data.get("public_url")),
        published_object_path=str(data.get("published_object_path") or ""),
        published_zip_created_at=_datetime_or_none(data.get("published_zip_created_at")),
        html_charset=str(data.get("html_charset") or "").strip(),
        enabled=bool(data.get("enabled", True)),
        archive_limit=_int_or_default(data.get("archive_limit"), settings.default_archive_limit),
        upload_max_total_mb=_int_or_default(data.get("upload_max_total_mb"), settings.default_upload_max_total_mb),
        upload_max_files=_int_or_default(data.get("upload_max_files"), settings.default_upload_max_files),
        upload_max_file_mb=_int_or_default(data.get("upload_max_file_mb"), settings.default_upload_max_file_mb),
    )


def get_site(db: firestore.Client, site_id: str) -> Site | None:
    validate_site_id(site_id)
    doc = get_collection(db, "sites").document(site_id).get()
    if not doc.exists:
        return None
    site = site_from_doc(doc)
    if not site.enabled:
        return None
    return site


def is_site_admin(db: firestore.Client, site_id: str, email: str) -> bool:
    validate_site_id(site_id)
    normalized = normalize_email(email)
    if not normalized:
        return False
    admin_doc = get_collection(db, "sites").document(site_id).collection("admins").document(normalized).get()
    if admin_doc.exists:
        return True
    for doc in get_collection(db, "sites").document(site_id).collection("admins").where("email", "==", normalized).limit(1).stream():
        return bool(doc.exists)
    return False


def list_admin_sites(db: firestore.Client, email: str) -> list[Site]:
    normalized = normalize_email(email)
    sites: list[Site] = []
    for doc in get_collection(db, "sites").stream():
        try:
            validate_site_id(doc.id)
        except ValueError:
            continue
        site = site_from_doc(doc)
        if not site.enabled:
            continue
        if is_site_admin(db, site.site_id, normalized):
            sites.append(site)
    sites.sort(key=lambda site: (site.name, site.site_id))
    return sites


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
