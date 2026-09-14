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
  description = "CIDRs allowed to reach port 22. Defaults to the whole internet; narrow it to your own address in terraform.tfvars once you are sure it is stable (a wrong value locks you out)."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
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
