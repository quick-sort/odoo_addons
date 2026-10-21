/** @odoo-module **/
import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        const cls = this.props.archInfo.className || "";
        this._isButtonMode = cls.includes("o_edit_toggle");
        if (this._isButtonMode) {
            this._archEditable = this.editable;
            this.editToggleState = useState({ active: false });
            this.editable = false;
        }
    },

    get editable() {
        if (this._isButtonMode && this.editToggleState) {
            return this.editToggleState.active ? this._archEditable : false;
        }
        return this._editable;
    },

    set editable(value) {
        this._editable = value;
    },

    toggleEditMode() {
        this.editToggleState.active = !this.editToggleState.active;
    },

    async onClickSave() {
        await super.onClickSave(...arguments);
        if (this._isButtonMode) {
            this.editToggleState.active = false;
        }
    },

    async onClickDiscard() {
        await super.onClickDiscard(...arguments);
        if (this._isButtonMode) {
            this.editToggleState.active = false;
        }
    },
});
