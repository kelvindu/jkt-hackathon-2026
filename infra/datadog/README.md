# Datadog Monitor + SRE Agent Webhook

Terraform ini membuat:

- Datadog webhook `@webhook-sre-agent` ke external NLB `sre-agent`.
- Monitor untuk metric `auth.errors.database_timeout`.
- Monitor-based SLO untuk demo Ops Ready Bonus.

Deploy:

```bash
cd infra/datadog
set -a
source ../../.env
set +a
export TF_VAR_datadog_api_key="$DD_API_KEY"
export TF_VAR_datadog_app_key="$DD_APP_KEY"
export TF_VAR_datadog_site="${DD_SITE:-datadoghq.com}"
export TF_VAR_team_name="${DD_LLMOBS_ML_APP:-ADMO}"
terraform init
terraform apply
```

Trigger demo:

```bash
kubectl -n hackathon delete job ops-simulator --ignore-not-found
kubectl apply -k ../../k8s/ops-simulator
```
