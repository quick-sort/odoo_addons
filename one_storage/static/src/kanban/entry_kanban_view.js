/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { EntryKanbanRenderer } from "./entry_kanban_renderer";

export const entryKanbanView = {
    ...kanbanView,
    Renderer: EntryKanbanRenderer,
};

registry.category("views").add("one_storage_entry_kanban", entryKanbanView);
