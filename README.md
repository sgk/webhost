# Webhost

GCSで公開する静的ウェブサイトを、管理者がZIPファイルで更新するための管理者専用Webアプリ。

## 開発環境

```bash
source ./activate.sh
python -m pip install -r requirements.txt
```

ローカル設定は `dot-env-example` をコピーして作る。

```bash
cp dot-env-example .env
```

開発サーバー:

```bash
make run
```

ローカル確認では `http://localhost:7000` を使う。

## Firestore

サイト定義:

```text
sites/{site_id}
  name
  public_bucket
  public_prefix
  public_url
  html_charset
  enabled
  archive_limit
  upload_max_total_mb
  upload_max_files
  upload_max_file_mb
```

サイト別管理者:

```text
sites/{site_id}/admins/{email}
  email
```

`site_id` は英小文字、数字、ハイフンで人間が決める。

パスワードログインを有効にする管理者は、先にサイト別管理者へ登録したうえで、対話式CLIから資格情報を登録する。

```bash
source ./activate.sh
python -m tools.set_admin_password admin@example.com
```

パスワードを省略するとランダムパスワードを発行し、Firestoreへの登録成功後に表示する。パスワードを指定する場合は `--password` を使う。

```bash
python -m tools.set_admin_password admin@example.com --password '12文字以上のパスワード'
```

`--password` の値はシェル履歴やプロセス一覧に残る可能性があるため、通常は自動発行を使う。資格情報は `admin_passwords/{メールアドレスのSHA-256}` に保存する。パスワードはランダムなソルトを使ったscryptハッシュとして保存し、平文は保存しない。同じコマンドを再実行するとパスワードを更新する。

`html_charset` は任意項目。設定した場合、stagingと公開時のHTMLレスポンスに `text/html; charset={html_charset}` を付ける。既存コンテンツの文字コードを変換する項目ではない。

`public_url` と `public_prefix` は末尾 `/` ありで登録する。

## GCS

履歴用バケットは1個だけ使う。

```text
gs://{SITE_HISTORY_BUCKET}/sites/{site_id}/current.zip
gs://{SITE_HISTORY_BUCKET}/sites/{site_id}/archive/{timestamp}-{hash}.zip
gs://{SITE_HISTORY_BUCKET}/sites/{site_id}/published.json
```

公開用バケットは共有バケットを使い、サイトごとのprefixで分離する。

```text
gs://{PUBLIC_BUCKET}/{public_prefix}/index.html
gs://{PUBLIC_BUCKET}/{public_prefix}/assets/app.css
```

共有公開バケット名をFirestoreの `public_bucket` に保存し、サイトごとの公開prefixを `public_prefix` に保存する。HTTPS公開では、Cloud Load BalancingのURL mapでhostごとにpath prefix rewriteを設定し、共有公開バケット内のサイトprefixへ向ける。

共有公開バケットには website main page suffix として `index.html` を設定する。これにより、ロードバランサー経由でディレクトリURLにアクセスした場合も、GCSがprefix配下の `index.html` を返す。

ZIPファイルは、ZIP直下に `index.html` がある形で作る。

```text
site.zip
  index.html
  assets/app.css
```

ディレクトリそのものをZIPに入れて `site/index.html` になる形は不可。

## Cloud Run

stagingはCloud Runインスタンス内の一時ディレクトリへ展開するため、最大インスタンス数は必ず `1` にする。

`make deploy` は `--max-instances 1` を指定する。

```bash
cp dot-env-example .env-deploy
make deploy
```

本番の `GOOGLE_OAUTH_CLIENT_SECRET` は `.env-deploy` に実値を書かず、Secret Manager に保存する。
手順は [docs/secrets.md](docs/secrets.md) を参照する。
