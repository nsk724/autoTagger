variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "instance_type" {
  description = "8 GB: the measured need of the full stack is about 4-5 GB"
  type        = string
  default     = "t3.large"
}

variable "root_volume_gb" {
  type    = number
  default = 40
}

variable "git_repo_url" {
  description = "https URL of the private GitHub repo"
  type        = string
}

variable "git_ref" {
  description = "tag or branch to deploy"
  type        = string
  default     = "main"
}

variable "dotenv_param_name" {
  description = "SecureString SSM parameter holding the whole .env (created by hand)"
  type        = string
  default     = "/triageiq/dotenv"
}

variable "admin_ssh_cidr" {
  description = "CIDR allowed to SSH; empty = no SSH rule (use SSM Session Manager)"
  type        = string
  default     = ""
}
