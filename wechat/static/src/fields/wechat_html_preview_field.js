/** @odoo-module **/

import { Component, useEffect, useRef } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * 只读渲染HTML正文的字段控件。
 *
 * 用于「企微应用消息」表单：消息已发送后正文不再需要编辑，直接把HTML渲染出来查看即可。
 * 渲染放在 srcdoc + sandbox 的 iframe 里（不加 allow-scripts，正文中的<script>不会执行），
 * 这样正文自带的样式不会污染后台表单，脚本也不会在已登录会话中被执行。
 * 与「预览正文」按钮打开的独立页面相比，这里只做同样的近似渲染，
 * 不会模拟企业微信服务端的清洗逻辑，最终效果仍以真实设备收到的消息为准。
 */

// iframe 内的基础样式，尽量接近企业微信客户端的阅读效果
const BASE_STYLE = `
    body {
        margin: 0;
        padding: 16px;
        background: #fff;
        color: #333;
        font-size: 17px;
        line-height: 1.75;
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica,
            "PingFang SC", "Hiragino Sans GB", "Microsoft Yahei", Arial, sans-serif;
        word-break: break-word;
    }
    img { max-width: 100% !important; height: auto !important; }
    table { max-width: 100%; border-collapse: collapse; }
    a { color: #576b95; }
`;

export class WechatHtmlPreviewField extends Component {
    static template = "odoo_wechat.WechatHtmlPreviewField";
    static props = {
        ...standardFieldProps,
        height: { type: Number, optional: true },
    };
    static defaultProps = {
        height: 600,
    };

    setup() {
        this.iframeRef = useRef("iframe");
        useEffect(
            () => {
                if (this.iframeRef.el) {
                    this.iframeRef.el.srcdoc = this.buildDocument();
                }
            },
            () => [this.value, this.iframeRef.el]
        );
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    buildDocument() {
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"/>' +
            '<meta name="viewport" content="width=device-width, initial-scale=1"/>' +
            '<base target="_blank"/>' +
            `<style>${BASE_STYLE}</style></head><body>${this.value}</body></html>`
        );
    }
}

export const wechatHtmlPreviewField = {
    component: WechatHtmlPreviewField,
    displayName: _t("企微正文预览"),
    supportedTypes: ["text", "html"],
    supportedOptions: [
        {
            label: _t("Height"),
            name: "height",
            type: "number",
            help: _t("预览区域高度，单位像素，默认600"),
        },
    ],
    extractProps: ({ options }) => ({
        height: options.height ? Number(options.height) : undefined,
    }),
};

registry.category("fields").add("wechat_html_preview", wechatHtmlPreviewField);
