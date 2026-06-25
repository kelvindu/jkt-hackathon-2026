output "account_id" {
  description = "AWS account used by Terraform."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "AWS region used by Terraform."
  value       = var.aws_region
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "kubeconfig_command" {
  description = "Command to configure kubectl for this cluster."
  value       = "aws eks update-kubeconfig --profile ${var.aws_profile} --region ${var.aws_region} --name ${aws_eks_cluster.this.name}"
}

output "datadog_namespace" {
  description = "Kubernetes namespace where the Datadog chart is installed."
  value       = helm_release.datadog.namespace
}
