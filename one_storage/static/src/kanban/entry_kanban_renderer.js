/** @odoo-module **/
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { EntryKanbanRecord } from "./entry_kanban_record";

export class EntryKanbanRenderer extends KanbanRenderer {
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: EntryKanbanRecord,
    };
}
