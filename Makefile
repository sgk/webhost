.PHONY: deploy run

deploy:
	@set -e; \
	ENV_FILE=.env-deploy; \
	if [ ! -f "$$ENV_FILE" ]; then \
		echo "$$ENV_FILE が見つかりません。"; \
		exit 1; \
	fi; \
	if [ -f ./bin/activate ]; then \
		. ./bin/activate; \
	fi; \
	PROJECT_ID=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --get GCP_PROJECT_ID); \
	SERVICE_NAME=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --get SERVICE_NAME); \
	REGION=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --get REGION); \
	SERVICE_ACCOUNT=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --get SERVICE_ACCOUNT); \
	ENV_VARS=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --env-vars); \
	SECRETS=$$(python tools/deploy_env.py --env-file "$$ENV_FILE" --secrets); \
	SECRET_ARGS=; \
	if [ -n "$$SECRETS" ]; then \
		SECRET_ARGS="--set-secrets $$SECRETS"; \
	fi; \
	if [ -z "$$PROJECT_ID" ] || [ -z "$$SERVICE_NAME" ] || [ -z "$$REGION" ] || [ -z "$$SERVICE_ACCOUNT" ]; then \
		echo "GCP_PROJECT_ID / SERVICE_NAME / REGION / SERVICE_ACCOUNT を $$ENV_FILE に設定してください。"; \
		exit 1; \
	fi; \
	gcloud run deploy "$$SERVICE_NAME" \
		--source . \
		--project "$$PROJECT_ID" \
		--region "$$REGION" \
		--service-account "$$SERVICE_ACCOUNT" \
		--allow-unauthenticated \
		--max-instances 1 \
		--set-build-env-vars GOOGLE_PYTHON_VERSION=3.13 \
		--set-env-vars "$$ENV_VARS" \
		$$SECRET_ARGS

run:
	@set -e; \
	ENV_FILE=.env; \
	if [ ! -f "$$ENV_FILE" ]; then \
		echo "$$ENV_FILE が見つかりません。"; \
		exit 1; \
	fi; \
	. "./$$ENV_FILE"; \
	if [ -f ./bin/activate ]; then \
		. ./bin/activate; \
	fi; \
	uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 7000
