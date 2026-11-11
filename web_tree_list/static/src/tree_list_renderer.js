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
        // Row selection is not part of the read-only tree contract.
        return this.isTreeMode ? false : super.hasSelectors;
    }

    get treeRows() {
        return this.props.list.model.treeRows;
    }

    onTreeGroupHeaderClicked(ev, group) {
        this.onGroupHeaderClicked(ev, group);
    }
}
