# The SSH key already exists in the DO account — reference, don't create.
data "digitalocean_ssh_key" "deployer" {
  name = var.ssh_key_name
}

resource "digitalocean_droplet" "app" {
  image      = "ubuntu-24-04-x64"
  name       = var.droplet_name
  region     = var.region
  size       = var.droplet_size
  ssh_keys   = [data.digitalocean_ssh_key.deployer.id]
  user_data  = file("${path.module}/cloud-init.yml")
  monitoring = true

  # cloud-init runs on first boot only; a later edit must not replace the droplet.
  lifecycle {
    ignore_changes = [user_data]
  }
}

# Inbound: SSH only. The Mini App is published by the funnel sidecar (Tailscale Funnel,
# an outbound tunnel), so it needs no inbound rule.
resource "digitalocean_firewall" "app" {
  name        = "${var.droplet_name}-fw"
  droplet_ids = [digitalocean_droplet.app.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
