/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { TreeListModel } from "./tree_list_model";
import { TreeListRenderer } from "./tree_list_renderer";

export const treeListView = {
    ...listView,
    Model: TreeListModel,
    Renderer: TreeListRenderer,
};

registry.category("views").add("tree_list", treeListView);
