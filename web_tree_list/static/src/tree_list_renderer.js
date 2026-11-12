/** @odoo-module **/

import { onWillRender } from "@odoo/owl";
import { ListRenderer } from "@web/views/list/list_renderer";

const MAX_DEPTH_CLASS = 20;

export class TreeListRenderer extends ListRenderer {
    static rowsTemplate = "web_tree_list.Rows";
    static leafRowTemplate = "web_tree_list.LeafRow";

    setup() {
        super.setup(...arguments);
        this._treeNodes = new Map();
        onWillRender(() => {
            this._treeNodes = new Map();
            if (this.isTreeMode) {
                for (const row of this.props.list.model.treeRows) {
                    this._treeNodes.set(row.record.resId, row);
                }
            }
        });
    }

    get isTreeMode() {
        return this.props.list.model.isTreeMode;
    }

    get hasSelectors() {
        // Row selection is not part of the read-only tree contract.
        return this.isTreeMode ? false : super.hasSelectors;
    }

    get treeRows() {
        return this.props.list.model.treeRows;
    }

    getRowClass(record) {
        const classes = super.getRowClass(record);
        if (!this.isTreeMode) {
            return classes;
        }
        const node = this._treeNodes.get(record.resId);
        if (!node) {
            return classes;
        }
        const extra = ["o_tree_node", `o_tree_depth_${Math.min(node.depth, MAX_DEPTH_CLASS)}`];
        if (node.group) {
            extra.push("o_tree_parent", node.group.isFolded ? "o_tree_folded" : "o_tree_open");
        }
        return `${classes} ${extra.join(" ")}`;
    }

    async onCellClicked(record, column, ev, newWindow) {
        if (this.isTreeMode) {
            const node = this._treeNodes.get(record.resId);
            const cell = ev.target.closest("td");
            if (
                node &&
                node.group &&
                cell &&
                cell === cell.parentElement.querySelector("td") &&
                this._isCaretClick(cell, node, ev)
            ) {
                ev.preventDefault();
                ev.stopPropagation();
                await node.group.toggle();
                return;
            }
        }
        return super.onCellClicked(record, column, ev, newWindow);
    }

    /** The expand/collapse arrow is drawn by CSS before the first cell content;
     * only clicks landing on that glyph area toggle the group. */
    _isCaretClick(cell, node, ev) {
        const indent =
            parseFloat(getComputedStyle(cell).getPropertyValue("--o-tree-indent")) || 18;
        const x = ev.clientX - cell.getBoundingClientRect().left;
        const caretStart = node.depth * indent;
        return x >= caretStart && x <= caretStart + indent;
    }
}
