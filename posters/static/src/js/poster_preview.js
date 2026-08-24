/** @odoo-module **/
import { Component, xml, useState, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";

const VIDEO_TYPES = new Set(["mp4", "webm", "mkv"]);
const IMAGE_TYPES = new Set(["png", "jpg", "gif"]);

class PosterPreviewDialog extends Component {
    static components = { Dialog };
    static props = ["title", "fileType", "mimeType", "url", "close"];
    static template = xml`
        <Dialog title="props.title" size="'fs'">
            <t t-if="props.fileType === 'pdf'">
                <iframe t-att-src="props.url" style="width:100%;height:75vh;border:0;display:block;"/>
            </t>
            <t t-elif="props.fileType === 'txt'">
                <pre style="white-space:pre-wrap;word-break:break-all;overflow:auto;max-height:75vh;margin:0;padding:8px;font-size:13px;font-family:monospace;" t-esc="state.text"/>
            </t>
            <t t-elif="isVideo">
                <video controls="controls" style="width:100%;max-height:75vh;display:block;background:#000;">
                    <source t-att-src="props.url" t-att-type="props.mimeType"/>
                </video>
            </t>
            <t t-elif="isImage">
                <div style="overflow:auto;max-height:75vh;text-align:center;background:#f0f0f0;">
                    <img t-att-src="props.url" style="max-width:100%;display:inline-block;"/>
                </div>
            </t>
        </Dialog>
    `;

    get isVideo() {
        return VIDEO_TYPES.has(this.props.fileType);
    }

    get isImage() {
        return IMAGE_TYPES.has(this.props.fileType);
    }

    setup() {
        this.state = useState({ text: "" });
        onWillStart(async () => {
            if (this.props.fileType === "txt") {
                const res = await fetch(this.props.url);
                this.state.text = await res.text();
            }
        });
    }
}

registry.category("actions").add("poster_preview_action", (env, action) => {
    const { poster_id, title, file_type, mime_type } = action.params;
    env.services.dialog.add(PosterPreviewDialog, {
        title,
        fileType: file_type,
        mimeType: mime_type,
        url: `/poster/preview/${poster_id}`,
    });
});
