# GCSウェブホスティング更新ツール 設計メモ

## 目的

GCSで公開する静的ウェブサイトを、管理者がZIPファイルで更新できる管理者専用Webアプリを作成する。

このアプリは新しいPython/FastAPIアプリとして作る。既存の `../mai` にある単一サイト向けのサイト更新機能を参考にするが、複数サイトを扱えるようにする。

## 前提

- Cloud Run上で動作する管理者専用Webサーバーとする。
- 管理者はGoogleアカウントで認証する。
- 全体管理者用の管理画面は作らない。
- サイト定義とサイトごとの管理者はFirestoreに置く。
- 1人の管理者が複数サイトを管理できる。
- ZIP履歴を置くGCSバケットは1個とする。
- 公開用GCSバケットはサイト数ぶん用意する。
- 公開用GCSバケットの中身は、このツールが全体を管理する。
- サイトIDは人間が決めてFirestoreに登録する。
- アプリ名、Cloud Runサービス名、GCPプロジェクトID、履歴用GCSバケット名などの具体名は未定のため、環境変数で受ける。

## Cloud Runインスタンス数

Cloud Runの最大インスタンス数は `1` にする。

staging確認サイトはCloud Runインスタンス内の一時ディレクトリへZIPを展開して配信する。Cloud Runのインスタンスが複数ある場合、ZIPを展開したインスタンスとstaging確認リクエストを受けるインスタンスが別になり、確認サイトが見えない可能性がある。

この問題を避けるため、このアプリではCloud Runの最大インスタンス数を `1` に固定する。インスタンス再起動、リビジョン切り替え、デプロイ、スケールゼロ復帰などで一時ディレクトリの内容が消えた場合は、管理画面から再度「確認サイトを用意する」を実行する運用とする。ZIP履歴と公開済みデータはGCSに残るため、データは失われない。

デプロイ設定では、Cloud Runに `--max-instances=1` を指定する。

## 画面

```text
/login
/logout
/auth/google
/auth/google/callback

/sites
/sites/{site_id}
/sites/{site_id}/staging/{path}
```

`/sites` は、ログイン中の管理者が管理できるサイトだけを一覧表示する。

`/sites/{site_id}` は、そのサイトのZIP履歴、staging準備、staging確認、本番公開、本番を空にする操作を提供する。

staging確認URLは管理画面配下の `/sites/{site_id}/staging/` とする。サイトごとの専用stagingホストは作らない。

## Firestore

サイト定義:

```text
sites/{site_id}
  name: string
  public_bucket: string
  public_url: string
  enabled: bool
  archive_limit: number
  upload_max_total_mb: number
  upload_max_files: number
  upload_max_file_mb: number
  created_at: timestamp
  updated_at: timestamp
```

サイト別管理者:

```text
sites/{site_id}/admins/{email}
  email: string
  created_at: timestamp
```

管理者セッション:

```text
admin_sessions/{token}
  email: string
  picture: string
  created_at: timestamp
  expires_at: timestamp
```

管理者セッションはFirestoreに保存する。Cookieにはランダムなセッショントークンだけを入れる。

## GCS

履歴用GCSバケットは1個だけ使う。サイトごとにprefixを分ける。

```text
gs://{history_bucket}/sites/{site_id}/current.zip
gs://{history_bucket}/sites/{site_id}/archive/{timestamp}-{hash}.zip
gs://{history_bucket}/sites/{site_id}/published.json
```

公開用GCSバケットはサイトごとに異なる。

```text
sites/{site_id}.public_bucket -> gs://{public_bucket}/...
```

## ZIPアップロードと履歴

- サイトごとの履歴は最大10件を標準とする。
- 上限は `sites/{site_id}.archive_limit` で変更できる。
- 自動削除はしない。
- 履歴数が上限に達した場合、新規アップロードは拒否する。
- 履歴ZIPは手動で削除できる。
- 公開中の履歴ZIPは削除できない。
- staging準備中の履歴ZIPを削除した場合は、準備済み状態を解除する。

ZIPについてアプリが確認する条件は最小限にする。

- ZIPファイルとして開けること。
- ZIP直下に `index.html` があること。

拡張子、HTML/CSS/JSの内容、外部リンク、スクリプトなどは検査しない。サイト管理者の責任範囲とする。

ただし、staging配信時はリクエストされたパスがstagingルート外へ出ないように拒否する。staging展開時も、実ファイルの書き込み先がstagingルート外になるものは書き込まない、またはエラーにする。

アップロード上限はサイト設定で変更できる。

```text
sites/{site_id}.upload_max_total_mb
sites/{site_id}.upload_max_files
sites/{site_id}.upload_max_file_mb
```

未設定時は環境変数のデフォルト値を使う。

## staging

stagingはCloud Runインスタンス内の一時ディレクトリへ展開する。

```text
{SITE_STAGING_DIR}/{site_id}/
{SITE_STAGING_DIR}/{site_id}.prepared
```

`{site_id}.prepared` には、現在stagingに準備されている履歴ZIPのオブジェクトパスを記録する。

本番公開前には、公開対象の履歴ZIPがstagingに準備済みであることを確認する。

## 本番公開

公開処理は、`../mai` の差分公開方式を参考にする。

1. 公開対象の履歴ZIPを選ぶ。
2. その履歴ZIPがstagingに準備済みであることを確認する。
3. `published.json` から現在公開中の履歴ZIPを取得する。
4. 現在公開中の履歴ZIPからmanifestを作る。
5. 実際の公開用GCSバケットの内容とmanifestが一致するか確認する。
6. 一致しない場合は公開を停止する。
7. 一致する場合は、新しいZIPとの差分を公開用GCSバケットへ反映する。
8. 新しいZIPに存在しない公開用GCSオブジェクトを削除する。
9. `published.json` を新しい履歴ZIPに更新する。

公開用GCSバケットはこのツールが全体を管理するため、ZIPに存在しない既存オブジェクトは削除してよい。

手動でGCSを変更した場合は、公開前の整合性確認で検出して停止する。

## 本番を空にする

「本番を空にする」機能は最初から作る。

動作:

1. ログインユーザーが対象サイトの管理者であることを確認する。
2. `sites/{site_id}.public_bucket` の全オブジェクトを削除する。
3. 空の `index.html` を置く。
4. 履歴バケットの `sites/{site_id}/published.json` に `__empty__` を記録する。

誤って空にした場合でも、履歴から再公開して復旧できる。

## 環境変数

```text
GCP_PROJECT_ID=
BASE_URL=
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
ADMIN_SESSION_TTL_HOURS=12

FIRESTORE_PREFIX=
SITE_HISTORY_BUCKET=
SITE_STAGING_DIR=/tmp/webhost-staging
SITE_SIGNED_URL_SERVICE_ACCOUNT=

DEFAULT_ARCHIVE_LIMIT=10
DEFAULT_UPLOAD_MAX_TOTAL_MB=200
DEFAULT_UPLOAD_MAX_FILES=2000
DEFAULT_UPLOAD_MAX_FILE_MB=50
```

デプロイ用には、少なくとも次の値も決める。

```text
SERVICE_NAME=
REGION=asia-northeast1
SERVICE_ACCOUNT=
MAX_INSTANCES=1
```

## 最初の実装範囲

最初の実装では次を作る。

- FastAPIの最小アプリ。
- 設定読み込み。
- Firestore接続。
- Google OAuthログイン。
- Firestore保存の管理者セッション。
- サイト一覧。
- サイト別権限判定。
- ZIPアップロード用署名付きURL。
- 履歴一覧。
- 履歴上限の確認。
- 履歴メモ。
- 履歴ZIPダウンロード。
- staging準備。
- staging配信。
- 本番公開。
- 本番を空にする。
- 履歴削除。
- README。
- 環境変数サンプル。
