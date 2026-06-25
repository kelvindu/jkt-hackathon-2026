variable "aws_profile" {
  description = "AWS CLI profile used by Terraform."
  type        = string
  default     = "hackathon"
}

variable "aws_region" {
  description = "AWS region for EKS and Bedrock in-region scoring."
  type        = string
  default     = "ap-southeast-3"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "jkt-hackathon-eks"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.33"
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_desired_size" {
  description = "Desired number of EKS worker nodes."
  type        = number
  default     = 1
}

variable "node_min_size" {
  description = "Minimum number of EKS worker nodes."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum number of EKS worker nodes."
  type        = number
  default     = 2
}

variable "datadog_api_key" {
  description = "Datadog API key used by the Datadog Helm chart."
  type        = string
  sensitive   = true
}

variable "datadog_site" {
  description = "Datadog site, for example datadoghq.com, datadoghq.eu, or ap1.datadoghq.com."
  type        = string
  default     = "datadoghq.com"
}

variable "team_name" {
  description = "Team name used for tags and resource metadata."
  type        = string
}

variable "datadog_chart_version" {
  description = "Optional Datadog Helm chart version. Leave null to use the latest chart from the repo at init/apply time."
  type        = string
  default     = null
}
