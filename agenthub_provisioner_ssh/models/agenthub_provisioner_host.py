from odoo import fields, models


class AgenthubProvisionerHost(models.Model):
    _inherit = "agenthub.provisioner.host"

    driver_type = fields.Selection(
        selection_add=[("ssh", "SSH")],
        ondelete={"ssh": "cascade"},
    )
    ssh_host = fields.Char(help="Target host name or IP address.")
    ssh_port = fields.Integer(default=22)
    ssh_user = fields.Char()
    ssh_private_key = fields.Text(groups="base.group_system")
    ssh_key_passphrase = fields.Char(groups="base.group_system")
    ssh_known_hosts = fields.Text(
        help="OpenSSH known_hosts content. Required when strict checking is on "
        "and the key is not in the container's system known_hosts."
    )
    ssh_strict_host_key = fields.Boolean(default=True)
    ssh_timeout = fields.Integer(default=15)
    remote_docker = fields.Char(default="docker")
