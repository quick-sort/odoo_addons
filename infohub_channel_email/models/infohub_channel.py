from odoo import fields, models


class InfohubChannel(models.Model):
    _inherit = "infohub.channel"

    channel_type = fields.Selection(
        selection_add=[("email", "Email")],
        ondelete={"email": "cascade"},
    )

    #: One channel collects from one receiving mailbox. Incoming mail is matched
    #: to a channel by this address, so several newsletters can share a single
    #: alias while still landing on different channels.
    email_to = fields.Char(
        string="Receiving Address",
        help="Address incoming newsletter emails are sent to. One channel per "
        "receiving inbox.",
    )
    split_items = fields.Boolean(
        string="Split into Items",
        default=False,
        help="Run the email splitter agent to break a digest email into one "
        "item per article. Leave off to store the whole email as a single item.",
    )
