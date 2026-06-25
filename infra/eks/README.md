# EKS + Datadog Helm

Terraform ini membuat EKS cluster kecil di AWS Jakarta (`ap-southeast-3`) memakai default VPC yang sudah tersedia di account hackathon, lalu meng-install Datadog Agent dan Datadog Cluster Agent via Helm.

## Prerequisites

- AWS CLI profile `hackathon` sudah login.
- Terraform, Helm, dan kubectl tersedia di mesin lokal.
- Datadog API key tersedia. Jangan commit file `.tfvars`.

## Deploy

```bash
cd infra/eks
terraform init
terraform plan \
  -var="team_name=<team-name>" \
  -var="datadog_api_key=<datadog-api-key>"
terraform apply \
  -var="team_name=<team-name>" \
  -var="datadog_api_key=<datadog-api-key>"
```

Jika Datadog org memakai site selain `datadoghq.com`, tambahkan:

```bash
-var="datadog_site=ap1.datadoghq.com"
```

## Verify

```bash
aws eks update-kubeconfig --profile hackathon --region ap-southeast-3 --name jkt-hackathon-eks
kubectl get nodes
kubectl -n datadog get pods
helm -n datadog status datadog
```

## Notes

- Terraform men-tag default subnet dengan tag Kubernetes ELB agar service `LoadBalancer` bisa memakai public subnet.
- Node group default memakai 2 node `t3.medium`; tipe ini tersedia di semua AZ Jakarta pada account yang dicek.
- Untuk production, pakai private subnet + NAT atau VPC endpoint. Untuk hackathon, default public subnet lebih cepat dan cukup untuk demo.
