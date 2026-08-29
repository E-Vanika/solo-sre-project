variable "tenancy_ocid" {
  description = "OCI tenancy OCID"
  type        = string
  sensitive   = true
}

variable "user_ocid" {
  description = "OCI user OCID"
  type        = string
  sensitive   = true
}

variable "fingerprint" {
  description = "OCI API key fingerprint"
  type        = string
  sensitive   = true
}

variable "private_key_path" {
  description = "Path to OCI API private key"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "OCI region"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key installed on the VM"
  type        = string
  sensitive   = true
}

variable "allowed_ssh_cidr" {
  description = "Public IPv4 or CIDR allowed to SSH; must not be within 0.0.0.0/8"
  type        = string

  default = "106.219.182.133/32"
}

variable "vcn_cidr" {
  description = "VCN CIDR"
  type        = string

  default = "10.0.0.0/16"
}