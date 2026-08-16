output "instance_id" {
  description = "OCI instance OCID"
  value       = oci_core_instance.free_vm.id
}

output "instance_name" {
  description = "Instance name"
  value       = oci_core_instance.free_vm.display_name
}

output "private_ip" {
  description = "Private IP address"
  value       = oci_core_instance.free_vm.private_ip
}

output "public_ip" {
  description = "Public IP address"
  value       = oci_core_instance.free_vm.public_ip
}

output "shape" {
  description = "OCI compute shape"
  value       = oci_core_instance.free_vm.shape
}

output "ssh_command" {
  description = "SSH command"
  value = format(
    "ssh -i ~/.ssh/id_ed25519 ubuntu@%s",
    oci_core_instance.free_vm.public_ip
  )
}