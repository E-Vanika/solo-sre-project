terraform {
  backend "oci" {
    bucket    = "cloud-playground-terraform-state-file"
    namespace = "axwj7qxpzppm"
    key       = "oci-free-vm/terraform.tfstate"
    region    = "ap-hyderabad-1"
  }
}