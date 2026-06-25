#!/usr/bin/env bash
# Build, push, and deploy the SRE agent (and friends) to EKS.
#
# Usage:
#   export ECR_REGISTRY=1234567890.dkr.ecr.us-east-1.amazonaws.com
#   export AWS_REGION=us-east-1
#   ./deploy.sh build           # build + push sre-agent (and auth-service/ops-simulator)
#   ./deploy.sh apply           # apply k8s manifests (expects secret.yaml to exist)
#   ./deploy.sh drill           # launch a chaos+security drill Job
#   ./deploy.sh all             # build + apply
set -euo pipefail

: "${ECR_REGISTRY:?set ECR_REGISTRY to your ECR registry host}"
AWS_REGION="${AWS_REGION:-us-east-1}"
TAG="${TAG:-latest}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS=hackathon

ecr_login() {
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY"
}

build_push() {
  local name="$1" context="$2"
  echo ">> building $name"
  docker build -t "$ECR_REGISTRY/$name:$TAG" "$context"
  docker push "$ECR_REGISTRY/$name:$TAG"
}

render() { sed "s|<ECR_REGISTRY>|$ECR_REGISTRY|g" "$1"; }

cmd_build() {
  ecr_login
  build_push sre-agent     "$ROOT/sre-agent"
  build_push auth-service  "$ROOT/auth-service"
  build_push ops-simulator "$ROOT/ops-simulator"
}

cmd_apply() {
  kubectl apply -f "$ROOT/sre-agent/k8s/namespace.yaml"
  kubectl apply -f "$ROOT/sre-agent/k8s/configmap.yaml"
  if [ -f "$ROOT/sre-agent/k8s/secret.yaml" ]; then
    kubectl apply -f "$ROOT/sre-agent/k8s/secret.yaml"
  else
    echo "!! k8s/secret.yaml not found — copy secret.example.yaml, fill it in, and re-run." >&2
    exit 1
  fi
  for f in auth-service deployment service hpa; do
    render "$ROOT/sre-agent/k8s/$f.yaml" | kubectl apply -f -
  done
  kubectl -n "$NS" rollout status deploy/sre-agent
  kubectl -n "$NS" rollout status deploy/auth-service
}

cmd_drill() {
  kubectl -n "$NS" delete job ops-simulator-drill --ignore-not-found
  render "$ROOT/sre-agent/k8s/ops-simulator-job.yaml" | kubectl apply -f -
  echo ">> tailing drill logs (Ctrl-C to stop)"
  sleep 3
  kubectl -n "$NS" logs -f job/ops-simulator-drill
}

case "${1:-all}" in
  build) cmd_build ;;
  apply) cmd_apply ;;
  drill) cmd_drill ;;
  all)   cmd_build; cmd_apply ;;
  *) echo "usage: $0 {build|apply|drill|all}" >&2; exit 2 ;;
esac
