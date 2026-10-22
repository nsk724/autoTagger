terraform {
  required_version = ">= 1.6"
  required_providers {
    cloudflare = { source = "cloudflare/cloudflare", version = "~> 5.28" }
    random     = { source = "hashicorp/random", version = "~> 3.9" }
  }
}

# token from env CLOUDFLARE_API_TOKEN: Account > Cloudflare Tunnel: Edit, Zone > DNS: Edit
provider "cloudflare" {}
