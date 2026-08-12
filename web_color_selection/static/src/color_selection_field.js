/** @odoo-module **/
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { CheckboxItem } from "@web/core/dropdown/checkbox_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { formatSelection } from "@web/views/fields/formatters";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * LabelEditSelectionField - badge style selection widget.
 * Shows colored badges in both readonly and edit mode.
 * Click to open dropdown with badge options.
 *
 * Usage:
 *   <field name="rating" widget="label_edit_selection"
 *          options="{'colors': {'red': 'danger', 'yellow': 'warning', 'green': 'success'}}"/>
 */
export class LabelEditSelectionField extends Component {
    static template = "web_color_selection.LabelEditSelectionField";
    static components = { Dropdown, CheckboxItem };
    static props = {
        ...standardFieldProps,
        colors: { type: Object, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = { colors: {} };

    get options() {
        return this.props.record.fields[this.props.name].selection;
    }
    get currentValue() {
        return this.props.record.data[this.props.name] || false;
    }
    get label() {
        if (!this.currentValue) return "";
        return formatSelection(this.currentValue, { selection: this.options });
    }
    get badgeClass() {
        return this.props.colors[this.currentValue] || "secondary";
    }
    async updateRecord(value) {
        await this.props.record.update(
            { [this.props.name]: value },
            { save: this.props.autosave }
        );
    }
}

registry.category("fields").add("label_edit_selection", {
    component: LabelEditSelectionField,
    displayName: _t("Label Edit Selection"),
    supportedTypes: ["selection"],
    extractProps({ options }, dynamicInfo) {
        return {
            colors: options.colors || {},
            autosave: "autosave" in options ? !!options.autosave : true,
            readonly: dynamicInfo.readonly,
        };
    },
});

/**
 * ColorSelectionField - dot style selection widget.
 * Shows colored dot + label, like state_selection but with custom colors.
 *
 * Usage:
 *   <field name="status" widget="color_selection"
 *          options="{'colors': {'blocked': 'danger', 'done': 'success'}}"/>
 */
export class ColorSelectionField extends Component {
    static template = "web_color_selection.ColorSelectionField";
    static components = { Dropdown, CheckboxItem };
    static props = {
        ...standardFieldProps,
        showLabel: { type: Boolean, optional: true },
        colors: { type: Object, optional: true },
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = { showLabel: true, colors: {} };

    get options() {
        return this.props.record.fields[this.props.name].selection;
    }
    get currentValue() {
        return this.props.record.data[this.props.name] || false;
    }
    get label() {
        if (!this.currentValue) return "";
        return formatSelection(this.currentValue, { selection: this.options });
    }
    colorClass(value) {
        const color = this.props.colors[value];
        if (!color || color.startsWith("#")) return "";
        return `o_color_${color}`;
    }
    colorStyle(value) {
        const color = this.props.colors[value];
        if (!color) return "";
        return color.startsWith("#") ? `background-color: ${color}` : "";
    }
    async updateRecord(value) {
        await this.props.record.update(
            { [this.props.name]: value },
            { save: this.props.autosave }
        );
    }
}

registry.category("fields").add("color_selection", {
    component: ColorSelectionField,
    displayName: _t("Color Selection"),
    supportedTypes: ["selection"],
    extractProps({ options }, dynamicInfo) {
        return {
            showLabel: "hide_label" in options ? !options.hide_label : true,
            colors: options.colors || {},
            autosave: "autosave" in options ? !!options.autosave : true,
            readonly: dynamicInfo.readonly,
        };
    },
});
