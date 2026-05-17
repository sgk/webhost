# GCPセットアップ手順

このドキュメントは、Webhostを新しいGCPプロジェクトへ導入するための手順をまとめる。特定環境のプロジェクトID、プロジェクト番号、課金アカウントID、個人アカウント、OAuthシークレットは記載しない。

## 前提

- GCPプロジェクトを作成できる権限がある。
- 課金アカウントをプロジェクトへ紐付けできる。
- Google Cloud SDKを利用できる。
- このリポジトリでは `source ./activate.sh` により、Google Cloud SDKの設定ディレクトリを `./.gcloud` に分離する。

以下の例では、環境ごとの値を変数で表す。

```bash
export PROJECT_ID=your-project-id
export REGION=asia-northeast1
export GCLOUD_CONFIG_NAME=webhost
export GCP_ACCOUNT=you@example.com
export SERVICE_NAME=webhost
export SERVICE_ACCOUNT_NAME=webhost-app
export SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export HISTORY_BUCKET="${PROJECT_ID}-history"
export PUBLIC_BUCKET="${PROJECT_ID}-public"
export ARTIFACT_REPOSITORY=webhost
export LOCAL_ORIGIN=http://localhost:7000
export PRODUCTION_ORIGIN=https://webhost.example.com
```

## 1. ローカルgcloud設定を分離する

`.env` を作り、プロジェクトごとのgcloud設定を使う。

```bash
cp dot-env-example .env
```

`.env` には少なくとも次を設定する。

```bash
export GCP_CONFIG_NAME=webhost
export GCP_PROJECT_ID=your-project-id
export GCP_ACCOUNT=you@example.com
```

有効化する。

```bash
source ./activate.sh
gcloud auth login
gcloud auth application-default login
```

## 2. GCPプロジェクトを作成する

既存プロジェクトを使う場合、この手順は不要。

```bash
gcloud projects create "${PROJECT_ID}" --name="${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"
gcloud auth application-default set-quota-project "${PROJECT_ID}"
```

## 3. 課金を紐付ける

課金アカウント一覧を確認する。

```bash
gcloud beta billing accounts list
```

利用する課金アカウントを紐付ける。

```bash
gcloud beta billing projects link "${PROJECT_ID}" \
  --billing-account=BILLING_ACCOUNT_ID
```

確認する。

```bash
gcloud beta billing projects describe "${PROJECT_ID}"
```

`billingEnabled: true` になっていることを確認する。

## 4. APIを有効化する

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  firestore.googleapis.com \
  datastore.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  storage.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  --project "${PROJECT_ID}"
```

## 5. Firestore Nativeを作成する

```bash
gcloud firestore databases create \
  --database="(default)" \
  --location="${REGION}" \
  --type=firestore-native \
  --project "${PROJECT_ID}"
```

既に作成済みの場合は、そのまま使う。

## 6. Cloud Run実行用サービスアカウントを作成する

```bash
gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
  --display-name="Webhost app" \
  --project "${PROJECT_ID}"
```

プロジェクト権限を付与する。

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/datastore.user

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/logging.logWriter
```

署名付きURL発行に必要な権限を付与する。

```bash
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/iam.serviceAccountTokenCreator \
  --project="${PROJECT_ID}"
```

ローカル開発でログイン中ユーザーが署名付きURLを発行する場合は、ユーザーにも付与する。

```bash
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
  --member="user:${GCP_ACCOUNT}" \
  --role=roles/iam.serviceAccountTokenCreator \
  --project="${PROJECT_ID}"
```

## 7. 履歴用GCSバケットを作成する

ZIP履歴用バケットは1個だけ使う。サイトごとの履歴はprefixで分離する。

```bash
gcloud storage buckets create "gs://${HISTORY_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

サービスアカウントに操作権限を付与する。

```bash
gcloud storage buckets add-iam-policy-binding "gs://${HISTORY_BUCKET}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/storage.objectAdmin
```

ローカル開発で署名付きURL経由のアップロードを確認する場合は、ユーザーにも付与する。

```bash
gcloud storage buckets add-iam-policy-binding "gs://${HISTORY_BUCKET}" \
  --member="user:${GCP_ACCOUNT}" \
  --role=roles/storage.objectAdmin
```

ローカル開発用CORSを設定する。

```bash
gcloud storage buckets update "gs://${HISTORY_BUCKET}" \
  --cors-file=config/gcs-cors-local.json
```

本番URLが決まったら、本番オリジンもCORSに追加する。

## 8. Artifact Registryを作成する

Cloud Runのコンテナイメージ用にDockerリポジトリを作成する。

```bash
gcloud artifacts repositories create "${ARTIFACT_REPOSITORY}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Webhost containers" \
  --project="${PROJECT_ID}"
```

## 9. Google OAuthを設定する

Google Cloud Consoleの Google Auth Platform で、OAuth同意画面とWebクライアントを作成する。

注意: `gcloud iam oauth-clients` はこのアプリのGoogleログインで使う通常の `accounts.google.com` 向けOAuthクライアントIDではない。`accounts.google.com/o/oauth2/v2/auth` で使うクライアントIDは、Google Auth Platform の「クライアント」画面でWebアプリケーションとして作成する。

承認済みリダイレクトURI:

```text
http://localhost:7000/auth/google/callback
https://your-production-host.example.com/auth/google/callback
```

承認済みの JavaScript 生成元:

```text
http://localhost:7000
https://your-production-host.example.com
```

本番ホストはCloud Runのカスタムドメイン、または運用で使う管理画面URLに合わせる。後から本番ホストを変えた場合は、OAuthクライアントのリダイレクトURIとJavaScript生成元も更新する。

作成した値を `.env` と `.env-deploy` に設定する。

```bash
export GOOGLE_OAUTH_CLIENT_ID=...
export GOOGLE_OAUTH_CLIENT_SECRET=...
```

本番では `BASE_URL` も設定する。

```bash
export BASE_URL=https://your-production-host.example.com
```

## 10. サイト公開用GCSバケットを作成する

公開用GCSバケットは共有バケットを作成し、サイトごとのprefixで分離する。

```bash
gcloud storage buckets create "gs://${PUBLIC_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

ディレクトリURLで `index.html` を返すため、website main page suffixを設定する。

```bash
gcloud storage buckets update "gs://${PUBLIC_BUCKET}" \
  --web-main-page-suffix=index.html
```

アプリのサービスアカウントに公開バケット操作権限を付与する。

```bash
gcloud storage buckets add-iam-policy-binding "gs://${PUBLIC_BUCKET}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/storage.objectAdmin
```

ロードバランサーのbackend bucketから公開するため、オブジェクト閲覧を公開する。

```bash
gcloud storage buckets add-iam-policy-binding "gs://${PUBLIC_BUCKET}" \
  --member=allUsers \
  --role=roles/storage.objectViewer
```

HTTPS公開では、Cloud Load Balancingのbackend bucketを共有公開バケットに対して作成する。URL mapはhostごとにpath prefix rewriteを設定し、リクエストをサイトprefix配下へ向ける。

例:

```text
site-a.example.com -> gs://{PUBLIC_BUCKET}/site-a.example.com/
site-b.example.com -> gs://{PUBLIC_BUCKET}/site-b.example.com/
```

URL mapの概念:

```text
host: site-a.example.com
  backend bucket: shared-public-bucket
  path prefix rewrite: /site-a.example.com/

host: site-b.example.com
  backend bucket: shared-public-bucket
  path prefix rewrite: /site-b.example.com/
```

backend bucketはサイトごとに作らない。Cloud Load Balancingのbackend bucket数クォータを避けるため、1つまたは少数のbackend bucketで複数サイトを公開する。

外部Application Load Balancerの概略:

```text
global address
  -> forwarding rule
  -> target HTTP(S) proxy
  -> URL map
  -> backend bucket
  -> gs://{PUBLIC_BUCKET}
```

URL mapではhostごとのroute ruleを作り、path prefix rewriteでサイトprefixを付ける。共有公開バケットの website main page suffix に `index.html` を設定しているため、rootやディレクトリURLだけの特別ルールは不要。

管理画面用Cloud Runのカスタムドメインは、この静的サイト公開用ロードバランサーとは別に扱う。

## 11. Firestoreにサイト定義と管理者を登録する

Firestoreにサイト定義を作成する。

```text
sites/{site_id}
  name: string
  public_bucket: string
  public_prefix: string
  public_url: string
  html_charset: string
  enabled: true
  archive_limit: 10
  upload_max_total_mb: 200
  upload_max_files: 2000
  upload_max_file_mb: 50
```

JSONで登録する場合の例:

```json
{
  "name": "Site A",
  "public_bucket": "your-public-bucket",
  "public_prefix": "site-a.example.com/",
  "public_url": "https://site-a.example.com/",
  "html_charset": "Shift_JIS",
  "enabled": true,
  "archive_limit": 10,
  "upload_max_total_mb": 200,
  "upload_max_files": 2000,
  "upload_max_file_mb": 50
}
```

`html_charset` は任意項目。設定すると、staging配信と公開時のHTML Content-Typeに `text/html; charset={html_charset}` を付ける。ファイル内容の文字コード変換はしない。UTF-8のHTMLだけを扱うサイトでは未設定でよい。

`published_object_path` と `published_zip_created_at` はアプリが公開処理時に更新する内部状態のため、初期登録時には設定しない。

サイト管理者を登録する。

```text
sites/{site_id}/admins/{admin_email}
  email: string
```

管理者を追加する場合は、対象サイトの `admins` サブコレクションにGoogleアカウントのメールアドレスを小文字で登録する。ドキュメントIDもメールアドレスにしておくと確認しやすい。

```json
{
  "email": "admin@example.com"
}
```

`site_id` は英小文字、数字、ハイフンで人間が決める。

各フィールドの意味:

```text
name
  画面表示用のサイト名。
public_bucket
  共有公開バケット名。gs:// は付けない。
public_prefix
  共有公開バケット内で、そのサイトを置くprefix。末尾 `/` あり。
public_url
  公開サイトのURL。末尾 `/` あり。
html_charset
  HTMLのContent-Typeへ付与するcharset。不要なら未設定。
enabled
  falseの場合はサイト一覧にも管理画面にも出さない。
archive_limit
  保存する履歴ZIPの最大数。上限到達時はアップロード不可。
upload_max_total_mb
  ZIP全体の展開後合計サイズ上限。
upload_max_files
  ZIP内ファイル数上限。
upload_max_file_mb
  ZIP内1ファイルあたりのサイズ上限。
```

`public_bucket` は共有公開バケット名を入れる。`public_prefix` はサイトごとの公開prefixを末尾 `/` ありで入れる。

例:

```text
sites/site-a
  public_bucket: your-public-bucket
  public_prefix: site-a.example.com/
  public_url: https://site-a.example.com/
```

## 12. ZIPファイルを作る

アップロードするZIPは、ZIP直下に `index.html` がある形にする。

```text
site.zip
  index.html
  assets/app.css
  images/logo.png
```

次のように、ディレクトリそのものをZIP化して `index.html` が一段下に入る形は不可。

```text
site.zip
  site/
    index.html
```

コマンドで作る場合は、サイトの公開ルートディレクトリへ移動してからZIP化する。

```bash
cd path/to/site-root
zip -r ../site.zip .
```

## 13. 環境変数を設定する

`.env` と `.env-deploy` に設定する。

```bash
export GCP_PROJECT_ID="${PROJECT_ID}"
export GCP_ACCOUNT="${GCP_ACCOUNT}"
export SERVICE_NAME="${SERVICE_NAME}"
export REGION="${REGION}"
export SERVICE_ACCOUNT="${SERVICE_ACCOUNT_EMAIL}"
export SITE_HISTORY_BUCKET="${HISTORY_BUCKET}"
export SITE_SIGNED_URL_SERVICE_ACCOUNT="${SERVICE_ACCOUNT_EMAIL}"
```

ローカル開発では:

```bash
export BASE_URL=http://localhost:7000
export FIRESTORE_PREFIX=dev
```

本番では:

```bash
export BASE_URL=https://your-production-host.example.com
export FIRESTORE_PREFIX=prod
```

`FIRESTORE_PREFIX` は環境ごとにFirestoreデータを分けたい場合に設定する。分離しない運用では空にする。

## 14. デプロイする

```bash
source ./activate.sh
make deploy
```

`make deploy` はCloud Runへ `--max-instances 1` を指定する。stagingはCloud Runインスタンス内の一時ディレクトリへ展開するため、最大インスタンス数は必ず1にする。

Cloud Runにカスタムドメインを割り当てる場合は、管理画面用のホスト名をCloud Runサービスにマッピングし、DNSにはCloud Runが指示するレコードを設定する。一般的なCNAME先は次の形になる。

```text
webhost.example.com. CNAME ghs.googlehosted.com.
```

HTTPSが有効になったら、`BASE_URL` とOAuthクライアントの本番リダイレクトURIがそのホスト名と一致していることを確認する。
