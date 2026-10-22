terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.70" }
  }
  # shortcut: local Terraform state, single operator only; move to an S3 backend with locking before a second person runs apply
}

provider "aws" {
  region = var.region
}
