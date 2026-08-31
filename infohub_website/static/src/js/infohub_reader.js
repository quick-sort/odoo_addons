/** @odoo-module **/

/**
 * 阅读界面的即时交互：收藏切换、标为未读、订阅表单的目标类型联动。
 *
 * 用 public_widget 而不是 OWL：这些都是渐进增强，页面本身由 QWeb 服务端渲染，
 * 没有 OWL 才能解决的状态管理问题。
 *
 * 后端端点是 type='jsonrpc'（Odoo 19 的正确写法），所以用 @web/core/network/rpc
 * 调用，CSRF 由 jsonrpc 机制本身处理，不需要手工带 token。
 */

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.InfohubReader = publicWidget.Widget.extend({
    selector: ".o_infohub_timeline, .o_infohub_item",
    events: {
        "click .o_infohub_star": "_onToggleStar",
        "click .o_infohub_unread": "_onMarkUnread",
    },

    /**
     * 收藏切换。乐观更新会让失败时状态错乱，所以等服务端返回再改样式。
     */
    async _onToggleStar(ev) {
        ev.preventDefault();
        const button = ev.currentTarget;
        const itemId = parseInt(button.dataset.itemId, 10);
        if (!itemId || button.disabled) {
            return;
        }
        button.disabled = true;
        try {
            const result = await rpc("/infohub/item/toggle_star", { item_id: itemId });
            button.classList.toggle("o_infohub_starred", !!result.is_starred);
        } finally {
            button.disabled = false;
        }
    },

    /**
     * 标为未读后跳回信息流：留在详情页会立刻被"打开即已读"改回去。
     */
    async _onMarkUnread(ev) {
        ev.preventDefault();
        const button = ev.currentTarget;
        const itemId = parseInt(button.dataset.itemId, 10);
        if (!itemId || button.disabled) {
            return;
        }
        button.disabled = true;
        await rpc("/infohub/item/mark_read", { item_id: itemId, read: false });
        window.location.href = "/infohub";
    },
});

/**
 * 订阅表单：按选择的类型只显示对应的目标下拉框。
 */
publicWidget.registry.InfohubSubscriptionForm = publicWidget.Widget.extend({
    selector: ".o_infohub_subscriptions",
    events: {
        "change .o_infohub_target_type": "_onTargetTypeChange",
    },

    start() {
        this._syncTargets();
        return this._super(...arguments);
    },

    _onTargetTypeChange() {
        this._syncTargets();
    },

    _syncTargets() {
        const select = this.el.querySelector(".o_infohub_target_type");
        if (!select) {
            return;
        }
        const wanted = `o_infohub_target_${select.value}`;
        this.el.querySelectorAll(".o_infohub_target").forEach((node) => {
            const active = node.classList.contains(wanted);
            node.classList.toggle("d-none", !active);
            // 隐藏的下拉框要禁用，否则会把无关的值一起 POST 上去
            node.querySelectorAll("select").forEach((field) => {
                field.disabled = !active;
            });
        });
    },
});

export default {
    InfohubReader: publicWidget.registry.InfohubReader,
    InfohubSubscriptionForm: publicWidget.registry.InfohubSubscriptionForm,
};
