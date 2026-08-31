import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { cookie } from "@web/core/browser/cookie";

import { standardFieldProps } from "../standard_field_props";
import { useInputField } from "../input_field_hook";

let renderSeq = 0;

export class MermaidField extends Component {
    static template = "web_widget_mermaid.MermaidField";
    static props = {
        ...standardFieldProps,
        securityLevel: { type: String, optional: true },
        theme: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        securityLevel: "strict",
        theme: "auto",
        placeholder: _t("graph TD\n    A --> B"),
    };

    setup() {
        this.containerRef = useRef("container");
        this.state = useState({ error: null });
        this._lastSource = null;

        onWillStart(async () => {
            await loadBundle("web_widget_mermaid.assets_lib");
            this.initializeMermaid();
        });

        useInputField({
            getValue: () => this.value,
            refName: "textarea",
        });

        useEffect(() => {
            if (this.props.readonly) {
                this.renderDiagram();
            }
        });
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    initializeMermaid() {
        const mermaid = window.mermaid;
        if (!mermaid) {
            return;
        }
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: this.props.securityLevel,
            theme: this.resolveTheme(),
        });
    }

    resolveTheme() {
        if (this.props.theme && this.props.theme !== "auto") {
            return this.props.theme;
        }
        return cookie.get("color_scheme") === "dark" ? "dark" : "default";
    }

    async renderDiagram() {
        const el = this.containerRef.el;
        if (!el || !window.mermaid) {
            return;
        }
        const source = this.value;
        if (source === this._lastSource) {
            return;
        }
        this._lastSource = source;
        el.innerHTML = "";
        this.state.error = null;
        if (!source.trim()) {
            return;
        }
        try {
            const id = `o_mermaid_svg_${renderSeq++}`;
            const { svg, bindFunctions } = await window.mermaid.render(id, source);
            if (bindFunctions) {
                bindFunctions(el);
            }
            el.innerHTML = svg;
        } catch (err) {
            this.state.error = this.formatError(err);
            this.cleanupStrayNodes();
        }
    }

    formatError(err) {
        const raw = (err && (err.str || err.message)) || String(err);
        return raw;
    }

    cleanupStrayNodes() {
        document
            .querySelectorAll("body > [id^='do_mermaid_svg_'], body > [id^='o_mermaid_svg_']")
            .forEach((node) => node.remove());
    }
}

export const mermaidField = {
    component: MermaidField,
    displayName: _t("Mermaid Diagram"),
    supportedTypes: ["text", "char"],
    supportedOptions: [
        {
            label: _t("Security level"),
            name: "security_level",
            type: "selection",
            choices: [
                { label: _t("Strict (default)"), value: "strict" },
                { label: _t("Loose"), value: "loose" },
                { label: _t("Sandbox"), value: "sandbox" },
            ],
        },
        {
            label: _t("Theme"),
            name: "theme",
            type: "string",
        },
        {
            label: _t("Placeholder (edit mode)"),
            name: "placeholder",
            type: "string",
        },
    ],
    extractProps: ({ options }) => ({
        securityLevel: options?.security_level,
        theme: options?.theme,
        placeholder: options?.placeholder,
    }),
};

registry.category("fields").add("mermaid", mermaidField);
