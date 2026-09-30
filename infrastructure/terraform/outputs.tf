output "droplet_ipv4" {
  value = digitalocean_droplet.app.ipv4_address
}

output "firewall_id" {
  value = digitalocean_firewall.app.id
}
