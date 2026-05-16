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

## Cloud Run

stagingはCloud Runインスタンス内の一時ディレクトリへ展開するため、最大インスタンス数は必ず `1` にする。

`make deploy` は `--max-instances 1` を指定する。

```bash
cp dot-env-example .env-deploy
make deploy
```
