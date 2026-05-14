#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  _ACTIVATE_PREV_OPTS=$(set +o)
fi

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ -f "${ROOT_DIR}/.env" ]; then
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/.env"
fi

if [ -f "${ROOT_DIR}/bin/activate" ]; then
  # shellcheck source=/dev/null
  source "${ROOT_DIR}/bin/activate"
else
  echo "venv not found: ${ROOT_DIR}/bin/activate" >&2
fi

export CLOUDSDK_CONFIG="${ROOT_DIR}/.gcloud"

if command -v gcloud >/dev/null 2>&1; then
  if [ -n "${GCP_CONFIG_NAME:-}" ]; then
    gcloud config configurations create "${GCP_CONFIG_NAME}" --no-activate >/dev/null 2>&1 || true
    gcloud config configurations activate "${GCP_CONFIG_NAME}"
  fi

  if [ -n "${GCP_PROJECT_ID:-}" ]; then
    gcloud config set project "${GCP_PROJECT_ID}"
  fi

  if [ -n "${GCP_ACCOUNT:-}" ]; then
    gcloud config set account "${GCP_ACCOUNT}"
  fi
else
  echo "gcloud not found; skipping gcloud config" >&2
fi

echo "Activated venv and gcloud config at ${CLOUDSDK_CONFIG}"

if [ -n "${_ACTIVATE_PREV_OPTS:-}" ]; then
  eval "${_ACTIVATE_PREV_OPTS}"
  unset _ACTIVATE_PREV_OPTS
fi

