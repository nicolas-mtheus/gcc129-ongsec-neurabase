#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "Error: kubectl was not found. Install kubectl and configure the local cluster first." >&2
  exit 1
fi

if ! kubectl get namespace ongsec >/dev/null 2>&1; then
  echo "Error: Namespace 'ongsec' does not exist. Apply base/namespace.yaml first." >&2
  exit 1
fi

generate_secret() {
  openssl rand -base64 24 2>/dev/null || head -c 24 /dev/urandom | base64
}

apply_local_secret() {
  local name="$1"
  shift

  if kubectl get secret "$name" --namespace ongsec >/dev/null 2>&1; then
    echo "Secret '$name' already exists. Skipping."
    return 0
  fi

  local literal_args=()
  for pair in "$@"; do
    literal_args+=(--from-literal="$pair")
  done

  kubectl create secret generic "$name" \
    --namespace ongsec \
    "${literal_args[@]}" >/dev/null

  echo "Secret '$name' created."
}

for service in org audit task badge; do
  password=$(generate_secret)
  apply_local_secret "${service}-db-credentials" \
    "POSTGRES_PASSWORD=${password}" \
    "DB_PASSWORD=${password}"
done

jwt_secret=$(generate_secret)
apply_local_secret "ongsec-app-credentials" \
  "JWT_SECRET=${jwt_secret}"

echo "Created local database and application Secrets in namespace 'ongsec'."

