output "instance_id" {
  value = aws_instance.host.id
}

output "ssm_session_command" {
  value = "aws ssm start-session --region ${var.region} --target ${aws_instance.host.id}"
}
