/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";

export class TreeListRenderer extends ListRenderer {
    static rowsTemplate = "web_tree_list.Rows";
    static leafRowTemplate = "web_tree_list.LeafRow";
    static treeGroupRowTemplate = "web_tree_list.GroupRow";

    get isTreeMode() {
        return this.props.list.model.isTreeMode;
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
