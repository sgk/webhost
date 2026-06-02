from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode

from fastapi import Request

SUPPORTED_LANGUAGES = {"ja", "en"}
DEFAULT_LANGUAGE = "ja"

MESSAGES: dict[str, dict[str, str]] = {
    "ja": {
        "logout": "ログアウト",
        "language.ja": "日本語",
        "language.en": "English",
        "login.title": "管理ログイン",
        "login.google": "Googleアカウントでログイン",
        "login.error.config": "Googleログインの設定が未完了です。",
        "login.error.failed": "Googleログインに失敗しました。",
        "login.error.state": "ログイン状態の検証に失敗しました。",
        "login.error.code": "ログインコードが取得できませんでした。",
        "login.error.verify": "Googleログインの検証に失敗しました。",
        "login.error.email": "確認済みのメールアドレスを取得できませんでした。",
        "login.error.no_sites": "管理できるサイトがないため、ログインできません。",
        "sites.title": "サイト一覧",
        "sites.aria": "管理サイト",
        "sites.site": "サイト",
        "sites.status": "公開状態",
        "sites.source_zip": "元ZIP",
        "sites.actions": "操作",
        "sites.unpublished": "未公開",
        "sites.manage": "管理",
        "sites.empty": "管理できるサイトはありません。",
        "site.back": "サイト一覧",
        "site.open_prod": "本番を開く",
        "site.open_staging": "確認サイト",
        "site.upload_title": "ZIPアップロード",
        "site.drop_title": "ZIPをここにドロップ",
        "site.drop_sub": "またはクリックして選択",
        "site.archive_title": "履歴",
        "site.reload": "再読み込み",
        "site.delete_selected": "選択した履歴を削除",
        "site.publish_empty": "本番を空にする",
        "site.published": "公開中",
        "site.loading_archives": "履歴を読み込んでいます...",
        "site.stop": "ストップ",
    },
    "en": {
        "logout": "Log out",
        "language.ja": "日本語",
        "language.en": "English",
        "login.title": "Admin Login",
        "login.google": "Sign in with Google",
        "login.error.config": "Google sign-in is not configured.",
        "login.error.failed": "Google sign-in failed.",
        "login.error.state": "Could not verify the sign-in state.",
        "login.error.code": "Could not get the sign-in code.",
        "login.error.verify": "Could not verify Google sign-in.",
        "login.error.email": "Could not get a verified email address.",
        "login.error.no_sites": "You cannot sign in because there are no manageable sites.",
        "sites.title": "Sites",
        "sites.aria": "Managed sites",
        "sites.site": "Site",
        "sites.status": "Published status",
        "sites.source_zip": "Source ZIP",
        "sites.actions": "Actions",
        "sites.unpublished": "Unpublished",
        "sites.manage": "Manage",
        "sites.empty": "No manageable sites.",
        "site.back": "Sites",
        "site.open_prod": "Open production",
        "site.open_staging": "Staging site",
        "site.upload_title": "ZIP Upload",
        "site.drop_title": "Drop ZIP here",
        "site.drop_sub": "or click to choose",
        "site.archive_title": "Archives",
        "site.reload": "Reload",
        "site.delete_selected": "Delete selected archives",
        "site.publish_empty": "Empty production",
        "site.published": "Published",
        "site.loading_archives": "Loading archives...",
        "site.stop": "Stop",
    },
}


def normalize_language(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE
    lang = value.strip().lower().split(",", 1)[0].split("-", 1)[0]
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def request_language(request: Request) -> str:
    query_lang = normalize_language(request.query_params.get("lang"))
    if request.query_params.get("lang"):
        return query_lang
    cookie_lang = request.cookies.get("webhost_lang")
    if cookie_lang:
        return normalize_language(cookie_lang)
    return normalize_language(request.headers.get("accept-language"))


def make_translator(lang: str) -> Callable[[str], str]:
    normalized = normalize_language(lang)

    def translate(key: str) -> str:
        return MESSAGES.get(normalized, MESSAGES[DEFAULT_LANGUAGE]).get(key, MESSAGES[DEFAULT_LANGUAGE].get(key, key))

    return translate


def language_url(request: Request, lang: str) -> str:
    query = dict(parse_qsl(request.url.query, keep_blank_values=True))
    query["lang"] = normalize_language(lang)
    encoded = urlencode(query)
    return f"{request.url.path}?{encoded}" if encoded else request.url.path
