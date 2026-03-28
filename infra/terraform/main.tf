terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}

variable "hcloud_token" {
  description = "Hetzner Cloud API Token"
  type        = string
  sensitive   = true
}

variable "cluster_name" {
  description = "Name of the k3s cluster"
  type        = string
  default     = "incident-commander"
}

variable "node_count" {
  description = "Number of nodes"
  type        = number
  default     = 3
}

variable "node_type" {
  description = "Hetzner server type"
  type        = string
  default     = "cx21"
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "nbg1"
}

provider "hcloud" {
  token = var.hcloud_token
}

# Private network
resource "hcloud_network" "cluster_net" {
  name     = "${var.cluster_name}-network"
  ip_range = "10.0.0.0/16"
}

resource "hcloud_network_subnet" "cluster_subnet" {
  network_id   = hcloud_network.cluster_net.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.1.0/24"
}

# SSH key (use existing or generate)
resource "hcloud_ssh_key" "default" {
  name       = "${var.cluster_name}-key"
  public_key = file("~/.ssh/id_rsa.pub")
}

# Server nodes
resource "hcloud_server" "node" {
  count       = var.node_count
  name        = "${var.cluster_name}-node-${count.index}"
  server_type = var.node_type
  image       = "ubuntu-22.04"
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.default.id]

  network {
    network_id = hcloud_network.cluster_net.id
    ip         = "10.0.1.${count.index + 10}"
  }

  labels = {
    cluster = var.cluster_name
    role    = count.index == 0 ? "master" : "worker"
  }

  depends_on = [hcloud_network_subnet.cluster_subnet]
}

# Load Balancer
resource "hcloud_load_balancer" "ingress" {
  name               = "${var.cluster_name}-lb"
  load_balancer_type = "lb11"
  location           = var.location
}

resource "hcloud_load_balancer_target" "lb_target" {
  count            = var.node_count
  load_balancer_id = hcloud_load_balancer.ingress.id
  type             = "server"
  server_id        = hcloud_server.node[count.index].id
}

resource "hcloud_load_balancer_service" "http" {
  load_balancer_id = hcloud_load_balancer.ingress.id
  protocol         = "http"
  listen_port      = 80
  destination_port = 80
}

resource "hcloud_load_balancer_service" "https" {
  load_balancer_id = hcloud_load_balancer.ingress.id
  protocol         = "tcp"
  listen_port      = 443
  destination_port = 443
}

# Outputs
output "node_ips" {
  value = hcloud_server.node[*].ipv4_address
}

output "load_balancer_ip" {
  value = hcloud_load_balancer.ingress.ipv4
}

output "master_ip" {
  value = hcloud_server.node[0].ipv4_address
}
