/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";

export class TreeListRenderer extends ListRenderer {
    static rowsTemplate = "web_tree_list.Rows";
    static leafRowTemplate = "web_tree_list.LeafRow";
    static treeGroupRowTemplate = "web_tree_list.GroupRow";

    get isTreeMode() {
        return this.props.list.model.isTreeMode;
    }

    get hasSelectors() {
        // No record selector in tree mode: the leaf rows reuse the native
        // RecordRow, and mounting its CheckBox component inside our recursive
        // t-call tree breaks Owl's block reconciliation ("bdom" is null).
        // Row selection is not part of the read-only tree contract anyway.
        return this.isTreeMode ? false : super.hasSelectors;
    }

    get treeRoots() {
        return this.props.list.model.treeRoots;
    }

    get treeParentMap() {
        return this.props.list.model.treeParentMap;
    }

    isTreeParent(record) {
        return this.treeParentMap.has(record.resId);
    }

    getTreeGroup(record) {
        return this.treeParentMap.get(record.resId);
    }

    onTreeGroupHeaderClicked(ev, group) {
        this.onGroupHeaderClicked(ev, group);
    }
}
