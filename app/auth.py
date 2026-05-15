from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
import threading
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import requests

from app.config import load_settings
from app.firestore import get_client, get_collection

settings = load_settings()
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_OAUTH_STATE_COOKIE = "admin_oauth_state"
ADMIN_OAUTH_NEXT_COOKIE = "admin_oauth_next"
ADMIN_LOGIN_PATH = "/login"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
SESSION_CACHE_SECONDS = 30

_session_cache: dict[str, tuple[datetime, dict]] = {}
_session_cache_lock = threading.Lock()


def _is_https(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto == "https"


def _base_url(request: Request) -> str:
    if settings.base_url:
        return settings.base_url
    return str(request.base_url).rstrip("/")


def _next_path(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return path


def _is_allowed_next_path(path: str | None) -> bool:
    if not path:
        return False
    return path == "/" or path.startswith("/sites")


def _normalize_next_path(path: str | None) -> str:
    if _is_allowed_next_path(path):
        return path or "/sites"
    return "/sites"


def login_url(next_path: str | None = None) -> str:
    normalized = _normalize_next_path(next_path)
    return f"{ADMIN_LOGIN_PATH}?next={quote(normalized)}"


def _render_login(request: Request, error: str | None = None, next_path: str | None = None) -> HTMLResponse:
    normalized = _normalize_next_path(next_path)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "title": "管理ログイン",
            "error": error,
            "auth_start_url": f"/auth/google?next={quote(normalized)}",
        },
    )


def _get_cached_session(token: str, now: datetime) -> dict | None:
    with _session_cache_lock:
        cached = _session_cache.get(token)
        if not cached:
            return None
        cache_expires_at, data = cached
        if cache_expires_at <= now:
            _session_cache.pop(token, None)
            return None
        return dict(data)


def _cache_session(token: str, data: dict, now: datetime) -> None:
    expires_at = data.get("expires_at")
    cache_expires_at = now + timedelta(seconds=SESSION_CACHE_SECONDS)
    if isinstance(expires_at, datetime) and expires_at < cache_expires_at:
        cache_expires_at = expires_at
    with _session_cache_lock:
        _session_cache[token] = (cache_expires_at, dict(data))


def _clear_cached_session(token: str) -> None:
    with _session_cache_lock:
        _session_cache.pop(token, None)


def get_admin_session(request: Request) -> dict | None:
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if not token:
        return None
    now = datetime.now(timezone.utc)
    cached = _get_cached_session(token, now)
    if cached:
        return cached
    db = get_client()
    doc = get_collection(db, "admin_sessions").document(token).get()
    if not doc.exists:
        _clear_cached_session(token)
        return None
    data = doc.to_dict() or {}
    expires_at = data.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < now:
        doc.reference.delete()
        _clear_cached_session(token)
        return None
    _cache_session(token, data, now)
    return data


def require_admin(request: Request) -> dict | RedirectResponse:
    session = get_admin_session(request)
    if not session:
        return RedirectResponse(url=login_url(_next_path(request)), status_code=303)
    return session


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    session = get_admin_session(request)
    if session:
        return RedirectResponse(url="/sites", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request, next: str | None = None):
    session = get_admin_session(request)
    if session:
        return RedirectResponse(url=_normalize_next_path(next), status_code=303)
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        return _render_login(request, "Googleログインの設定が未完了です。", next)
    return _render_login(request, None, next)


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if token:
        _clear_cached_session(token)
        db = get_client()
        get_collection(db, "admin_sessions").document(token).delete()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE)
    return response


@router.get("/auth/google")
async def auth_google(request: Request, next: str | None = None):
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        return _render_login(request, "Googleログインの設定が未完了です。", next)
    state = secrets.token_urlsafe(16)
    normalized_next = _normalize_next_path(next)
    redirect_uri = f"{_base_url(request)}/auth/google/callback"
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }
    response = RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=303)
    response.set_cookie(
        ADMIN_OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    response.set_cookie(
        ADMIN_OAUTH_NEXT_COOKIE,
        quote(normalized_next),
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    return response


@router.get("/auth/google/callback", response_class=HTMLResponse)
async def auth_google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    next_cookie = request.cookies.get(ADMIN_OAUTH_NEXT_COOKIE, "")
    next_path = _normalize_next_path(unquote(next_cookie) if next_cookie else "")
    if error:
        return _render_login(request, "Googleログインに失敗しました。", next_path)
    state_cookie = request.cookies.get(ADMIN_OAUTH_STATE_COOKIE, "")
    if not state or state != state_cookie:
        return _render_login(request, "ログイン状態の検証に失敗しました。", next_path)
    if not code:
        return _render_login(request, "ログインコードが取得できませんでした。", next_path)

    redirect_uri = f"{_base_url(request)}/auth/google/callback"
    token_response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    if not token_response.ok:
        return _render_login(request, "Googleログインに失敗しました。", next_path)
    token_data = token_response.json()
    id_token = token_data.get("id_token")
    if not id_token:
        return _render_login(request, "Googleログインに失敗しました。", next_path)

    info_response = requests.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=10)
    if not info_response.ok:
        return _render_login(request, "Googleログインに失敗しました。", next_path)
    info = info_response.json()
    if info.get("aud") != settings.google_oauth_client_id:
        return _render_login(request, "Googleログインの検証に失敗しました。", next_path)

    email = str(info.get("email") or "").strip().lower()
    if not email or info.get("email_verified") not in ("true", True):
        return _render_login(request, "確認済みのメールアドレスを取得できませんでした。", next_path)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.admin_session_ttl_hours)
    token = secrets.token_urlsafe(32)
    session = {
        "email": email,
        "picture": info.get("picture"),
        "created_at": now,
        "expires_at": expires_at,
    }
    db = get_client()
    get_collection(db, "admin_sessions").document(token).set(session)
    _cache_session(token, session, now)

    response = RedirectResponse(url=next_path, status_code=303)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=settings.admin_session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    response.delete_cookie(ADMIN_OAUTH_STATE_COOKIE)
    response.delete_cookie(ADMIN_OAUTH_NEXT_COOKIE)
    return response


async def admin_context_middleware(request: Request, call_next):
    session = get_admin_session(request)
    if session:
        request.state.admin_email = session.get("email")
        request.state.admin_picture = session.get("picture")
    return await call_next(request)
