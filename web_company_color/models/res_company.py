# Copyright 2019 Alexandre Díaz <dev@redneboa.es>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import base64
from colorsys import hls_to_rgb, rgb_to_hls

from odoo import api, fields, models

from odoo.addons.base.models.assetsbundle import ScssStylesheetAsset

from ..utils import convert_to_image, image_to_rgb, n_rgb_to_hex

URL_BASE = "/web_company_color/static/src/scss/"
URL_SCSS_GEN_TEMPLATE = URL_BASE + "custom_colors.%d.gen.scss"


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_scss_template(self):
        return """
        .o_main_navbar {
          background: %(color_navbar_bg)s !important;
          background-color: %(color_navbar_bg)s !important;
          border-bottom: 1px solid %(color_navbar_border_bottom)s !important;
          color: %(color_navbar_text)s !important;

          .show {
            .dropdown-toggle {
              background-color: %(color_navbar_bg_hover)s !important;
            }
          }

          > ul {
            > li {
              > a, > label {
                color: %(color_navbar_text)s !important;

                &:hover, &:focus, &:active, &:focus:active {
                  background-color: %(color_navbar_bg_hover)s !important;
                }
              }
            }
          }
        }
          a[href],
          a[tabindex],
          .btn-link,
          .o_external_button {
            color: %(color_link_text)s !important;
            .o_main_navbar {
            color: none;
            }
          }
        a:hover,
        .btn-link:hover {
          color: %(color_link_text_hover)s !important;
          .o_main_navbar {
            color: none;
          }
        }
        .o_main_navbar a.o_menu_brand[href] {
            color: %(color_navbar_text)s !important;
        }
        .oe_login_form a {
          color: %(color_link_text)s !important;
          &:hover {
            color: %(color_link_text_hover)s !important;
          }
        }
        .btn-primary:not(.disabled),
        .ui-autocomplete .ui-menu-item > a.ui-state-active {
          color: %(color_button_text)s !important;
          background-color: %(color_button_bg)s !important;
          border-color: %(color_button_bg)s !important;
        }
        .btn-primary:hover:not(.disabled),
        .ui-autocomplete .ui-menu-item > a.ui-state-active:hover {
          color: %(color_button_text)s !important;
          background-color: %(color_button_bg_hover)s !important;
          border-color: %(color_button_bg_hover)s !important;
        }
        .o_searchview .o_searchview_facet .o_searchview_facet_label {
          color: %(color_button_text)s !important;
          background-color: %(color_button_bg)s !important;
        }
        .o_form_view .o_horizontal_separator {
          color: %(color_link_text)s !important;
        }
        .o_form_view .oe_button_box .oe_stat_button .o_button_icon,
        .o_form_view .oe_button_box .oe_stat_button .o_stat_info .o_stat_value,
        .o_form_view .oe_button_box .oe_stat_button > span .o_stat_value {
          color: %(color_link_text)s !important;
        }
        .o_form_view .o_form_statusbar > .o_statusbar_status >
        .o_arrow_button.btn-primary.disabled {
          color: %(color_link_text)s !important;
        }
        .o_required_modifier{
          :focus-within {
            --o-input-border-color: %(color_button_bg)s !important;
            --o-caret-color: %(color_button_bg)s !important;
          }
          input:hover, .o_field_many2one_selection:hover {
            --o-input-border-color: %(color_button_bg)s !important;
            --o-caret-color: %(color_button_bg)s !important;
          }
        }
        .o_menu_sections .o_nav_entry {
          background: %(color_navbar_bg)s !important;
          background-color: %(color_navbar_bg)s !important;
          color: %(color_navbar_text)s !important;
          &:hover, &:focus, &:active, &:focus:active {
            background-color: %(color_navbar_bg_hover)s !important;
          }
          border-bottom: 1px solid %(color_navbar_border_bottom)s !important;
        }
        .o_menu_sections .dropdown-toggle {
          background: %(color_navbar_bg)s !important;
          background-color: %(color_navbar_bg)s !important;
          color: %(color_navbar_text)s !important;
          &:hover, &:focus, &:active, &:focus:active {
            background-color: %(color_navbar_bg_hover)s !important;
          }
          border-bottom: 1px solid %(color_navbar_border_bottom)s !important;
        }
        .o_menu_systray button,
        .o_navbar_breadcrumbs,
        .o_main_navbar button,
        .o_menu_toggle {
            color: %(color_navbar_text)s !important;
            &:hover, &:focus, &:active, &:focus:active {
                background-color: %(color_navbar_bg_hover)s !important;
            }
        }
        .dropdown-item{
            color: %(color_submenu_text)s !important;
        }
        :root .o_grid_apps_menu {
            --app-menu-background: url(/web_responsive/static/src/img/home-menu-bg-overlay.svg), linear-gradient(to bottom, %(color_button_bg_light)s, white) !important;
        }
        .o_loading_indicator {
            background-color: %(color_navbar_bg)s !important;
        }
        .form-check-input:checked {
            background-color: %(color_button_bg)s !important;
            border-color: %(color_button_bg)s !important;
        }
        .o_cp_switch_buttons .btn.selected {
            border-color: %(color_button_bg)s !important;
            color: %(color_button_bg)s !important;
        }
        :root {
            --bs-primary: %(color_button_bg)s !important;
            --bs-primary-rgb: %(color_button_bg_rgb)s !important;
            --o-cc1-btn-primary: %(color_button_bg)s;
            --o-cc1-btn-primary-border: %(color_button_bg)s;
            --o-cc2-btn-primary: %(color_button_bg)s;
            --o-cc2-btn-primary-border: %(color_button_bg)s;
            --primary-bg-subtle: %(color_button_bg_light)s;
            scrollbar-color: %(color_button_bg)s transparent;
        }
        .btn-outline-primary {
            color: %(color_button_bg)s !important;
            border-color: %(color_button_bg)s !important;
            &:hover, &:active, &.active {
                background-color: %(color_button_bg)s !important;
                color: %(color_button_text)s !important;
            }
        }
        .text-primary {
            color: %(color_button_bg)s !important;
        }
        .text-action {
            color: %(color_button_bg)s !important;
        }
        .o-dropdown.btn-secondary.show,
        .o-dropdown.btn-outline-secondary.show {
            border-color: %(color_button_bg)s !important;
            background-color: %(color_button_bg_light)s !important;
        }
        .btn-secondary {
            --btn-active-border-color: %(color_button_bg)s;
            --btn-active-bg: %(color_button_bg_light)s;
        }
        .btn-outline-secondary {
            --btn-active-border-color: %(color_button_bg)s;
            --btn-active-bg: %(color_button_bg_light)s;
        }
        .o_field_statusbar > .o_statusbar_status,
        .o_field_statusbar_duration > .o_statusbar_status,
        .o_field_rotting_statusbar_duration > .o_statusbar_status {
            --o-statusbar-background-active: %(color_button_bg_light)s;
            --o-statusbar-border-active: %(color_button_bg)s;
        }
        .progress {
            --bs-progress-bar-bg: %(color_button_bg)s;
        }
        .bg-primary {
            background-color: %(color_button_bg)s !important;
        }
        .o_datetime_picker .o_selected {
            background: %(color_button_bg_light)s !important;
        }
        .o-mail-Chatter-top:has(.o-mail-Chatter-sendMessage.active) .o-mail-Composer {
            background-color: %(color_button_bg_light)s !important;
        }
        .oe_button_box .oe_stat_button .o_button_icon {
            color: %(color_button_bg)s !important;
        }
        .o-form-buttonbox {
            --o-stat-text-color: %(color_button_bg)s;
            --o-stat-button-color: %(color_button_bg)s;
        }
        .o_tour_pointer {
            --TourPointer__color: %(color_button_bg)s;
            --TourPointer__color-accent: %(color_button_bg_accent)s;
        }
    """

    company_colors = fields.Serialized()
    color_navbar_bg = fields.Char("Navbar Background Color", sparse="company_colors")
    color_navbar_bg_hover = fields.Char(
        "Navbar Background Color Hover", sparse="company_colors"
    )
    color_navbar_border_bottom = fields.Char(
        "Navbar Bottom Border Color", sparse="company_colors"
    )
    color_navbar_text = fields.Char("Navbar Text Color", sparse="company_colors")
    color_button_text = fields.Char("Button Text Color", sparse="company_colors")
    color_button_bg = fields.Char("Button Background Color", sparse="company_colors")
    color_button_bg_hover = fields.Char(
        "Button Background Color Hover", sparse="company_colors"
    )
    color_link_text = fields.Char("Link Text Color", sparse="company_colors")
    color_link_text_hover = fields.Char(
        "Link Text Color Hover", sparse="company_colors"
    )
    color_submenu_text = fields.Char("Submenu Text Color", sparse="company_colors")
    scss_modif_timestamp = fields.Char("SCSS Modif. Timestamp")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.scss_create_or_update_attachment()
        return records

    def unlink(self):
        IrAttachmentObj = self.env["ir.attachment"]
        for record in self:
            IrAttachmentObj.sudo().search(
                [("url", "=", record.scss_get_url()), ("company_id", "=", record.id)]
            ).sudo().unlink()
        return super().unlink()

    def write(self, values):
        result = super().write(values)
        if not self.env.context.get("ignore_company_color"):
            fields_to_check = ["company_colors"] + [
                field_name
                for field_name, field in self._fields.items()
                if field.sparse == "company_colors"
            ]
            if any(field in values for field in fields_to_check):
                self.scss_create_or_update_attachment()
        return result

    def button_compute_color(self):
        self.ensure_one()
        values = self.default_get(
            ["color_navbar_bg", "color_navbar_bg_hover", "color_navbar_text"]
        )
        if self.logo:
            _r, _g, _b = image_to_rgb(convert_to_image(self.logo))
            # Make color 10% darker
            _h, _l, _s = rgb_to_hls(_r, _g, _b)
            _l = max(0, _l - 0.1)
            _rd, _gd, _bd = hls_to_rgb(_h, _l, _s)
            # Calc. optimal text color (b/w)
            # Grayscale human vision perception (Rec. 709 values)
            _a = 1 - (0.2126 * _r + 0.7152 * _g + 0.0722 * _b)
            values.update(
                {
                    "color_navbar_bg": n_rgb_to_hex(_r, _g, _b),
                    "color_navbar_bg_hover": n_rgb_to_hex(_rd, _gd, _bd),
                    "color_navbar_border_bottom": n_rgb_to_hex(_rd, _gd, _bd),
                    "color_navbar_text": "#000" if _a < 0.5 else "#fff",
                }
            )
        self.update(values)

    def _scss_get_sanitized_values(self):
        self.ensure_one()
        # Clone company_color as dictionary to avoid ORM operations
        # This allow extend company_colors and only sanitize selected fields
        # or add custom values
        values = dict(self.company_colors or {})
        values.update(
            {
                "color_navbar_bg": (values.get("color_navbar_bg") or "$o-brand-odoo"),
                "color_navbar_bg_hover": (values.get("color_navbar_bg_hover")),
                "color_navbar_border_bottom": values.get("color_navbar_border_bottom")
                or f"darken({values.get('color_navbar_bg') or '$o-brand-odoo'}, 10%)",
                "color_navbar_text": (values.get("color_navbar_text") or "#FFF"),
                "color_button_bg": values.get("color_button_bg") or "#71639e",
                "color_button_bg_hover": values.get("color_button_bg_hover")
                or "darken(#71639e, 10%)",
                "color_button_text": values.get("color_button_text") or "#FFF",
                "color_link_text": values.get("color_link_text") or "#71639e",
                "color_link_text_hover": values.get("color_link_text_hover")
                or "darken(#71639e, 10%)",
                "color_submenu_text": values.get("color_link_text") or "#374151",
            }
        )
        # Compute RGB values for CSS variables
        button_bg = values.get("color_button_bg", "#71639e")
        try:
            bg = button_bg.lstrip("#")
            r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
            values["color_button_bg_rgb"] = f"{r}, {g}, {b}"
            # Light version (mix 20% color with white)
            values["color_button_bg_light"] = f"#{int(r + (255 - r) * 0.8):02x}{int(g + (255 - g) * 0.8):02x}{int(b + (255 - b) * 0.8):02x}"
            # Slightly lighter version for tour pointer accent (~lighten 10%)
            values["color_button_bg_accent"] = f"#{min(255, int(r * 1.25)):02x}{min(255, int(g * 1.25)):02x}{min(255, int(b * 1.25)):02x}"
        except (ValueError, IndexError):
            values["color_button_bg_rgb"] = "113, 99, 158"
            values["color_button_bg_light"] = "#dddbe8"
            values["color_button_bg_accent"] = "#8a7bb2"
        return values

    def _scss_generate_content(self):
        self.ensure_one()
        # ir.attachment need files with content to work
        if not self.company_colors:
            return "// No Web Company Color SCSS Content\n"
        return self._get_scss_template() % self._scss_get_sanitized_values()

    def scss_get_url(self):
        self.ensure_one()
        return URL_SCSS_GEN_TEMPLATE % self.id

    def scss_create_or_update_attachment(self):
        IrAttachmentObj = self.env["ir.attachment"]
        for record in self:
            custom_url = record.scss_get_url()
            SCSS_asset = ScssStylesheetAsset(
                "web_company_color.company_color_assets", url=custom_url
            )
            compiled_CSS = SCSS_asset.compile(record._scss_generate_content())
            datas = base64.b64encode(compiled_CSS.encode("utf-8"))
            custom_attachment = IrAttachmentObj.sudo().search(
                [("url", "=", custom_url), ("company_id", "=", record.id)]
            )
            values = {
                "datas": datas,
                "url": custom_url,
                "name": custom_url,
                "company_id": record.id,
                "type": "binary",
                "mimetype": "text/css",
            }
            if custom_attachment:
                custom_attachment.sudo().write(values)
            else:
                IrAttachmentObj.sudo().create(values)
        self.env.registry.clear_cache()
