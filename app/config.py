from __future__ import annotations

from dataclasses import dataclass
import os


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value is not None else default


def _get_int_env(name: str, default: int) -> int:
    value = _get_env(name)
    if value is None or not value.strip():
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    base_url: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    admin_session_ttl_hours: int
    firestore_prefix: str
    site_history_bucket: str
    site_staging_dir: str
    site_signed_url_service_account: str
    default_archive_limit: int
    default_upload_max_total_mb: int
    default_upload_max_files: int
    default_upload_max_file_mb: int


def load_settings() -> Settings:
    return Settings(
        gcp_project_id=_get_env("GCP_PROJECT_ID", "") or "",
        base_url=(_get_env("BASE_URL", "") or "").rstrip("/"),
        google_oauth_client_id=_get_env("GOOGLE_OAUTH_CLIENT_ID", "") or "",
        google_oauth_client_secret=_get_env("GOOGLE_OAUTH_CLIENT_SECRET", "") or "",
        admin_session_ttl_hours=_get_int_env("ADMIN_SESSION_TTL_HOURS", 12),
        firestore_prefix=_get_env("FIRESTORE_PREFIX", "") or "",
        site_history_bucket=_get_env("SITE_HISTORY_BUCKET", "") or "",
        site_staging_dir=_get_env("SITE_STAGING_DIR", "/tmp/webhost-staging") or "/tmp/webhost-staging",
        site_signed_url_service_account=_get_env("SITE_SIGNED_URL_SERVICE_ACCOUNT", "") or "",
        default_archive_limit=_get_int_env("DEFAULT_ARCHIVE_LIMIT", 10),
        default_upload_max_total_mb=_get_int_env("DEFAULT_UPLOAD_MAX_TOTAL_MB", 200),
        default_upload_max_files=_get_int_env("DEFAULT_UPLOAD_MAX_FILES", 2000),
        default_upload_max_file_mb=_get_int_env("DEFAULT_UPLOAD_MAX_FILE_MB", 50),
    )

