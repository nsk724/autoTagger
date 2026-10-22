output "tunnel_token" {
  description = "put in .env as TUNNEL_TOKEN"
  value       = data.cloudflare_zero_trust_tunnel_cloudflared_token.triageiq.token
  sensitive   = true
}

output "url" {
  value = "https://${var.hostname}"
}
