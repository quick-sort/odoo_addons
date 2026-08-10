/** @odoo-module **/
import { CANCEL_GLOBAL_CLICK, KanbanRecord } from "@web/views/kanban/kanban_record";
import { FileModel } from "@web/core/file_viewer/file_model";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";

/**
 * FileModel backed by a one.storage.entry served from our own preview route.
 * The base FileModel.urlRoute targets /web/content|image/<id>; we point it at
 * /one_storage/entry/<id>/preview (inline disposition) so FileViewer can render
 * txt/image/pdf in <img>/<iframe>.
 */
class EntryFileModel extends FileModel {
    constructor(record) {
        super();
        this.id = record.resId;
        this.name = record.data.name;
        this.mimetype = record.data.mimetype;
    }
    get urlRoute() {
        return `/one_storage/entry/${this.id}/preview`;
    }
}

export class EntryKanbanRecord extends KanbanRecord {
    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    /**
     * Files open the FileViewer preview (txt/image/pdf); directories and
     * non-viewable files fall back to the default behavior (descend / open
     * the form).
     */
    onGlobalClick(ev) {
        if (ev.target.closest(CANCEL_GLOBAL_CLICK)) {
            return;
        }
        const record = this.props.record;
        if (record.data.is_dir) {
            return super.onGlobalClick(...arguments);
        }
        const model = new EntryFileModel(record);
        if (model.isViewable) {
            this.fileViewer.open(model);
            return;
        }
        return super.onGlobalClick(...arguments);
    }
}
