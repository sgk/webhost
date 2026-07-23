#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re

from app.firestore import get_client, get_collection, list_admin_sites, normalize_email, utcnow
from app.password_auth import generate_password, hash_password, password_document_id

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+$")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="サイト管理者のパスワード認証用資格情報をFirestoreへ登録・更新します。"
    )
    parser.add_argument("email", help="サイト管理者として登録済みのメールアドレス")
    parser.add_argument(
        "--password",
        help="使用するパスワード。省略時はランダムパスワードを発行します。",
    )
    args = parser.parse_args()

    email = normalize_email(args.email)
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        parser.error("メールアドレスの形式が不正です。")

    db = get_client()
    if not list_admin_sites(db, email):
        parser.error("このメールアドレスが管理する有効なサイトはありません。先にサイト管理者を登録してください。")

    generated = args.password is None
    password = generate_password() if generated else args.password

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        parser.error(str(exc))

    credentials = get_collection(db, "admin_passwords")
    document = credentials.document(password_document_id(email))
    action = "更新" if document.get().exists else "登録"
    answer = input(f"{email} のパスワード資格情報を{action}しますか？ [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("中止しました。")
        return 1

    document.set(
        {
            "email": email,
            "password_hash": password_hash,
            "enabled": True,
            "updated_at": utcnow(),
        }
    )
    print(f"{email} のパスワード資格情報を{action}しました。")
    if generated:
        print(f"発行パスワード: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
