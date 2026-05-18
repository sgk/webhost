# シークレット運用

このドキュメントは、本番 Cloud Run で使う秘密情報の置き場所と、値を変更するときの手順をまとめる。
秘密情報の実値は、このリポジトリのファイルには書かない。

## 基本方針

本番 Cloud Run の秘密情報は Secret Manager に置く。
Cloud Run には通常の環境変数ではなく、Secret Manager の参照として渡す。

対象の秘密情報:

- `GOOGLE_OAUTH_CLIENT_SECRET`

対応する Secret Manager の Secret:

| 環境変数 | Secret 名 |
| --- | --- |
| `GOOGLE_OAUTH_CLIENT_SECRET` | `webhost-app-google-oauth-client-secret` |

`GOOGLE_OAUTH_CLIENT_ID` は秘密情報ではないため、通常の環境変数として扱う。

## `.env-deploy` の扱い

`.env-deploy` は本番デプロイ用の設定ファイルだが、秘密情報の実値は書かない。
Secret Manager を使う対象として、次のようなプレースホルダだけを置く。

```bash
export GOOGLE_OAUTH_CLIENT_SECRET=secret-manager
```

`make deploy` は、この項目の値を Cloud Run の通常環境変数には渡さない。
代わりに `tools/deploy_env.py` が固定の Secret Manager 参照を生成し、`gcloud run deploy --set-secrets` に渡す。

確認:

```bash
python3 tools/deploy_env.py --env-file .env-deploy --secrets
```

期待する出力:

```text
GOOGLE_OAUTH_CLIENT_SECRET=webhost-app-google-oauth-client-secret:latest
```

## `.env` の扱い

`.env` はローカル開発用。
ローカルで Google OAuth を試す場合だけ、ローカル用の秘密情報を書く。
通常の画面確認だけなら、秘密情報はプレースホルダのままでよい。

`.env` と `.env-deploy` は Git にコミットしない。

## 本番用シークレットを変更する手順

本番用シークレットを変更したら、Secret Manager に新しいバージョンを追加してから Cloud Run を再デプロイする。
Cloud Run は `latest` を参照しているが、既存リビジョンの稼働中インスタンスへ値を差し替える運用にはしない。
必ず新しいリビジョンを作って反映する。

### 1. 新しい値を Secret Manager に追加する

値をコマンド履歴に残さないため、`read -rsp` で入力する。

```bash
read -rsp "GOOGLE_OAUTH_CLIENT_SECRET: " GOOGLE_OAUTH_CLIENT_SECRET
echo
printf '%s' "$GOOGLE_OAUTH_CLIENT_SECRET" | gcloud secrets versions add webhost-app-google-oauth-client-secret \
  --project="${GCP_PROJECT_ID}" \
  --data-file=-
unset GOOGLE_OAUTH_CLIENT_SECRET
```

### 2. Cloud Run に反映する

```bash
source ./activate.sh
make deploy
```

`make deploy` は `.env-deploy` を読み、Secret Manager の `latest` を参照する新しい Cloud Run リビジョンを作る。

### 3. 反映状態を確認する

Cloud Run の最新リビジョンと Secret 参照を確認する。

```bash
gcloud run services describe "${SERVICE_NAME}" \
  --project="${GCP_PROJECT_ID}" \
  --region="${REGION}" \
  --format='yaml(spec.template.spec.containers[0].env,status.latestReadyRevisionName,status.traffic)'
```

`GOOGLE_OAUTH_CLIENT_SECRET` が `valueFrom.secretKeyRef` になっていることを確認する。

最後に、人間がブラウザで次を確認する。

- 本番の `/login` から Google ログインできる。

## Google OAuth クライアントシークレットのローテーション順序

1. Google Cloud Console で対象 OAuth クライアントのシークレットを再生成する。
2. Secret Manager の `webhost-app-google-oauth-client-secret` に新しいバージョンを追加する。
3. `make deploy` で Cloud Run の新リビジョンを作る。
4. 本番の `/login` からログインできることを確認する。

## 初回作成時だけ必要な作業

Secret が存在しない環境では、最初に Secret Manager API を有効化する。

```bash
gcloud services enable secretmanager.googleapis.com \
  --project="${GCP_PROJECT_ID}"
```

Secret を作成する。

```bash
read -rsp "GOOGLE_OAUTH_CLIENT_SECRET: " GOOGLE_OAUTH_CLIENT_SECRET
echo
printf '%s' "$GOOGLE_OAUTH_CLIENT_SECRET" | gcloud secrets create webhost-app-google-oauth-client-secret \
  --project="${GCP_PROJECT_ID}" \
  --replication-policy=automatic \
  --data-file=-
unset GOOGLE_OAUTH_CLIENT_SECRET
```

Cloud Run 実行サービスアカウントに Secret を読む権限を付ける。

```bash
gcloud secrets add-iam-policy-binding webhost-app-google-oauth-client-secret \
  --project="${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role=roles/secretmanager.secretAccessor
```

## Secret のバージョン確認

Secret のバージョン一覧を確認する。

```bash
gcloud secrets versions list webhost-app-google-oauth-client-secret \
  --project="${GCP_PROJECT_ID}"
```

古い Secret バージョンは、Google OAuth 側の旧シークレットを無効化または削除したあとに無効化する。

```bash
gcloud secrets versions disable VERSION_ID \
  --secret=SECRET_NAME \
  --project="${GCP_PROJECT_ID}"
```

`VERSION_ID` と `SECRET_NAME` は、無効化する対象を確認してから指定する。
