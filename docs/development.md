# 開発環境

## 有効化

このプロジェクトでは、Python仮想環境とGoogle Cloud SDKの設定ディレクトリをプロジェクトごとに分離する。

作業前に次を実行する。

```bash
source ./activate.sh
```

有効化後、Pythonはリポジトリ直下の仮想環境を使う。

```bash
which python3
# <repository-root>/bin/python3
```

Google Cloud SDKは、このプロジェクト専用の設定ディレクトリを使う。

```bash
echo "$CLOUDSDK_CONFIG"
# <repository-root>/.gcloud
```

これにより、他プロジェクトの `gcloud` 設定や認証状態と混ざらない。

## 環境変数

`.env` はローカル専用ファイルとして扱い、Git管理しない。必要な項目は `dot-env-example` をコピーして設定する。

```bash
cp dot-env-example .env
```

主な項目:

```bash
export GCP_CONFIG_NAME=webhost
export GCP_PROJECT_ID=your-project-id
export GCP_ACCOUNT=you@example.com
```

`activate.sh` は `.env` を読み込んだ後、次を行う。

1. Python仮想環境を有効化する。
2. `CLOUDSDK_CONFIG` を `./.gcloud` に設定する。
3. `GCP_CONFIG_NAME` があれば、そのgcloud構成を作成または有効化する。
4. `GCP_PROJECT_ID` があれば、gcloudのprojectを設定する。
5. `GCP_ACCOUNT` があれば、gcloudのaccountを設定する。

`.env-deploy` は本番デプロイ専用として扱う。
本番の `GOOGLE_OAUTH_CLIENT_SECRET` は Secret Manager に置き、`.env-deploy` には実値を書かない。
詳しくは [シークレット運用](secrets.md) を参照する。

## gcloud認証

このプロジェクト専用のgcloud設定を有効化した状態で認証する。

```bash
source ./activate.sh
gcloud auth login
gcloud auth application-default login
```

認証情報は `./.gcloud` 配下に保存される。

## 依存関係

依存関係は `requirements.txt` に記載する。

```bash
source ./activate.sh
python -m pip install -r requirements.txt
python -m pip check
```
