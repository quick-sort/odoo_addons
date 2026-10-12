/** @odoo-module */

import { Component, markup, onWillStart, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class MarkdownField extends Component {
    static template = "web_widget_markdown.MarkdownField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        placeholder: "",
    };

    setup() {
        this.state = useState({ mode: "edit" });
        onWillStart(async () => {
            await loadBundle("web_widget_markdown.assets_lib");
        });
        useInputField({
            getValue: () => this.value,
            refName: "textarea",
        });
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    // Rendered markdown, sanitized before it is marked as trusted HTML. Never
    // returned for t-raw: t-out + markup() is the safe path.
    get previewHtml() {
        const raw = window.marked?.parse(this.value) ?? "";
        const clean = window.DOMPurify?.sanitize(raw) ?? "";
        return markup(clean);
    }

    get editLabel() {
        return _t("Edit");
    }

    get previewLabel() {
        return _t("Preview");
    }

    onEdit() {
        this.state.mode = "edit";
    }

    onPreview() {
        this.state.mode = "preview";
    }
}

export const markdownField = {
    component: MarkdownField,
    displayName: _t("Markdown"),
    supportedTypes: ["text", "char"],
    supportedOptions: [
        {
            label: _t("Placeholder"),
            name: "placeholder",
            type: "string",
        },
    ],
    extractProps: ({ options }) => ({
        placeholder: options?.placeholder,
    }),
};

registry.category("fields").add("markdown", markdownField);
