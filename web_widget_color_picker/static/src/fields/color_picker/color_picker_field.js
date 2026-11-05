import { Component } from "@odoo/owl";
import { ColorList } from "@web/core/colorlist/colorlist";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const COLOR_INDICES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

/**
 * Integer color-index field widget that collapses to the current color and
 * saves as soon as a color is picked.
 *
 * The core ``color_picker`` expands every swatch in editable lists and only
 * updates the record without saving, while ``kanban_color_picker`` always
 * expands and highlights based on the ``color`` field. Neither can be used
 * to set an arbitrary integer color field from a list.
 *
 * Usage:
 *   <field name="color_index" widget="compact_color_picker"/>
 */
export class CompactColorPickerField extends Component {
    static template = "web_widget_color_picker.CompactColorPickerField";
    static components = { ColorList };
    static props = { ...standardFieldProps };

    get colors() {
        return COLOR_INDICES;
    }

    get selectedColor() {
        return this.props.record.data[this.props.name] || 0;
    }

    onColorSelected(colorIndex) {
        return this.props.record.update(
            { [this.props.name]: colorIndex },
            { save: true }
        );
    }
}

registry.category("fields").add("compact_color_picker", {
    component: CompactColorPickerField,
    displayName: _t("Compact Color Picker"),
    supportedTypes: ["integer"],
});
