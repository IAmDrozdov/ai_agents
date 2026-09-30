variable "do_token" {
  description = "DigitalOcean API token (export TF_VAR_do_token=$DO_API_KEY from repo .env)"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "DigitalOcean region slug"
  type        = string
  default     = "fra1"
}

variable "droplet_size" {
  description = "Droplet size slug. s-1vcpu-1gb ($6/mo) fits two Python services; s-1vcpu-512mb-10gb ($4/mo) risks OOM."
  type        = string
  default     = "s-1vcpu-1gb"
}

variable "ssh_allowed_cidrs" {
  description = "Static CIDRs allowed to reach port 22. Normally empty: infrastructure/ssh-gate.sh opens the port for one address at a time (ADR-017). Set it only as a break-glass when the gate cannot be used."
  type        = list(string)
  default     = []
}

variable "droplet_name" {
  description = "Droplet (and firewall) name"
  type        = string
  default     = "ai-agents"
}

variable "ssh_key_name" {
  description = "Name of an SSH key ALREADY registered in your DigitalOcean account (doctl compute ssh-key list, or the control panel). Required; set it in terraform.tfvars."
  type        = string
}
