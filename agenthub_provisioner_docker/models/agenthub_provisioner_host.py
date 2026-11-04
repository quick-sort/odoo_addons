from odoo import fields, models


class AgenthubProvisionerHost(models.Model):
    _inherit = "agenthub.provisioner.host"

    driver_type = fields.Selection(
        selection_add=[("docker", "Docker")],
        ondelete={"docker": "cascade"},
    )
    docker_url = fields.Char(
        default="unix:///var/run/docker.sock",
        help="Docker Engine endpoint: unix:// or tcp:// (TLS required off-loopback).",
    )
    docker_timeout = fields.Integer(default=30)
    docker_tls = fields.Boolean(help="Use TLS for a tcp:// endpoint.")
    docker_tls_ca = fields.Char(help="CA certificate path inside the Odoo container.")
    docker_tls_cert = fields.Char(help="Client certificate path.")
    docker_tls_key = fields.Char(help="Client private key path.")
