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
export ARTIFACT_REPOSITORY=webhost
export LOCAL_ORIGIN=http://localhost:7000
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

公開用GCSバケットはサイトごとに作成する。

```bash
export SITE_ID=example-site
export PUBLIC_BUCKET=your-public-bucket

gcloud storage buckets create "gs://${PUBLIC_BUCKET}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --uniform-bucket-level-access
```

アプリのサービスアカウントに公開バケット操作権限を付与する。

```bash
gcloud storage buckets add-iam-policy-binding "gs://${PUBLIC_BUCKET}" \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role=roles/storage.objectAdmin
```

GCS静的ホスティングやLoad Balancer公開の構成は、公開方法に合わせて別途設定する。

## 11. Firestoreにサイト定義と管理者を登録する

Firestoreにサイト定義を作成する。

```text
sites/{site_id}
  name: string
  public_bucket: string
  public_url: string
  enabled: true
  archive_limit: 10
  upload_max_total_mb: 200
  upload_max_files: 2000
  upload_max_file_mb: 50
```

サイト管理者を登録する。

```text
sites/{site_id}/admins/{admin_email}
  email: string
```

`site_id` は英小文字、数字、ハイフンで人間が決める。

## 12. 環境変数を設定する

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
export FIRESTORE_PREFIX=
```

## 13. デプロイする

```bash
source ./activate.sh
make deploy
```

`make deploy` はCloud Runへ `--max-instances 1` を指定する。stagingはCloud Runインスタンス内の一時ディレクトリへ展開するため、最大インスタンス数は必ず1にする。
