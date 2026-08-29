# ============================================================
# AVAILABILITY DOMAINS
# ============================================================

data "oci_identity_availability_domains" "e2_micro_ads" {
  compartment_id = var.tenancy_ocid
}

# ============================================================
# UBUNTU IMAGE FOR E2 MICRO
# ============================================================

data "oci_core_images" "ubuntu_e2_micro" {
  compartment_id = var.tenancy_ocid

  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"

  shape = "VM.Standard.E2.1.Micro"

  sort_by    = "TIMECREATED"
  sort_order = "DESC"
}

# ============================================================
# VCN
# ============================================================

resource "oci_core_vcn" "e2_micro_vcn" {
  compartment_id = var.tenancy_ocid

  display_name = "e2-micro-sre-vcn"

  cidr_blocks = [
    "10.0.0.0/16"
  ]

  dns_label = "e2microvcn"

  freeform_tags = {
    ManagedBy   = "Terraform"
    Workload    = "SRE-DevOps-Lab"
    Environment = "Lab"
    Tier        = "Always-Free"
  }
}

# ============================================================
# INTERNET GATEWAY
# ============================================================

resource "oci_core_internet_gateway" "e2_micro_igw" {
  compartment_id = var.tenancy_ocid

  vcn_id = oci_core_vcn.e2_micro_vcn.id

  display_name = "e2-micro-sre-igw"

  enabled = true

  freeform_tags = {
    ManagedBy = "Terraform"
  }
}

# ============================================================
# ROUTE TABLE
# ============================================================

resource "oci_core_route_table" "e2_micro_route_table" {
  compartment_id = var.tenancy_ocid

  vcn_id = oci_core_vcn.e2_micro_vcn.id

  display_name = "e2-micro-sre-route-table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.e2_micro_igw.id
  }

  freeform_tags = {
    ManagedBy = "Terraform"
  }
}

# ============================================================
# SECURITY LIST
# ============================================================

resource "oci_core_security_list" "e2_micro_security_list" {
  compartment_id = var.tenancy_ocid

  vcn_id = oci_core_vcn.e2_micro_vcn.id

  display_name = "e2-micro-sre-security-list"

  # ----------------------------------------------------------
  # SSH - ONLY FROM YOUR ALLOWED PUBLIC IP
  # ----------------------------------------------------------

  ingress_security_rules {
    protocol = "6"

    source = var.allowed_ssh_cidr

    tcp_options {
      min = 22
      max = 22
    }

    description = "SSH from administrator public IP"
  }

  # ----------------------------------------------------------
  # ICMP - INSIDE VCN
  # ----------------------------------------------------------

  ingress_security_rules {
    protocol = "1"

    source = "10.0.0.0/16"

    description = "ICMP inside VCN"
  }

  # ----------------------------------------------------------
  # HTTP
  # Required for future Nginx/reverse-proxy projects
  # ----------------------------------------------------------

  ingress_security_rules {
    protocol = "6"

    source = "0.0.0.0/0"

    tcp_options {
      min = 80
      max = 80
    }

    description = "HTTP for future DevOps projects"
  }

  # ----------------------------------------------------------
  # HTTPS
  # Required for future TLS/reverse-proxy projects
  # ----------------------------------------------------------

  ingress_security_rules {
    protocol = "6"

    source = "0.0.0.0/0"

    tcp_options {
      min = 443
      max = 443
    }

    description = "HTTPS for future DevOps projects"
  }

  # ----------------------------------------------------------
  # OUTBOUND
  #
  # OCI default egress behavior is retained.
  # ----------------------------------------------------------
  egress_security_rules {
    protocol = "all"

    destination = "0.0.0.0/0"

    description = "Allow all outbound traffic"
  }
  freeform_tags = {
    ManagedBy = "Terraform"
  }
}

# ============================================================
# SUBNET
# ============================================================

resource "oci_core_subnet" "e2_micro_subnet" {
  compartment_id = var.tenancy_ocid

  vcn_id = oci_core_vcn.e2_micro_vcn.id

  display_name = "e2-micro-sre-subnet"

  cidr_block = "10.0.1.0/24"

  route_table_id = oci_core_route_table.e2_micro_route_table.id

  security_list_ids = [
    oci_core_security_list.e2_micro_security_list.id
  ]

  dns_label = "e2micro"

  prohibit_public_ip_on_vnic = false

  freeform_tags = {
    ManagedBy = "Terraform"
  }
}

# ============================================================
# ALWAYS FREE E2 MICRO VM
# ============================================================

resource "oci_core_instance" "e2_micro_vm" {
  compartment_id = var.tenancy_ocid

  display_name = "e2-micro-sre-lab"

  availability_domain = (
    data.oci_identity_availability_domains.e2_micro_ads.availability_domains[0].name
  )

  # ==========================================================
  # ALWAYS FREE E2 MICRO
  # ==========================================================

  shape = "VM.Standard.E2.1.Micro"

  # ==========================================================
  # VNIC
  # ==========================================================

  create_vnic_details {
    subnet_id = oci_core_subnet.e2_micro_subnet.id

    assign_public_ip = true

    hostname_label = "e2micro"
  }

  # ==========================================================
  # UBUNTU
  # ==========================================================

  source_details {
    source_type = "image"

    source_id = data.oci_core_images.ubuntu_e2_micro.images[0].id

    boot_volume_size_in_gbs = 50
  }

  # ==========================================================
  # SSH KEY
  # ==========================================================

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }

  # ==========================================================
  # TAGS
  # ==========================================================

  freeform_tags = {
    ManagedBy   = "Terraform"
    Workload    = "SRE-DevOps-Portfolio"
    Environment = "Lab"
    Shape       = "VM.Standard.E2.1.Micro"
    Tier        = "Always-Free"
    Lifecycle   = "Permanent"
  }
}