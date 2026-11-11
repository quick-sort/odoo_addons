/** @odoo-module **/

import { RelationalModel } from "@web/model/relational_model/relational_model";

export class TreeListModel extends RelationalModel {
    /**
     * A self-referencing many2one group-by field (e.g. parent_id) is rendered
     * as a recursive tree instead of the default single flat level.
     */
    get isTreeMode() {
        const groupBy = this.config.groupBy;
        if (!groupBy || groupBy.length !== 1) {
            return false;
        }
        const field = this.config.fields[groupBy[0].split(":")[0]];
        return Boolean(
            field && field.type === "many2one" && field.relation === this.config.resModel
        );
    }

    async load(params = {}) {
        await super.load(params);
        if (this.isTreeMode) {
            await this._loadTreeRoots();
        }
    }

    /**
     * The flat groups only expose each parent value as a separate top-level
     * group. The tree is rebuilt top-down from the "false" group (records whose
     * parent_id is false), so its records have to be loaded eagerly to serve as
     * the roots.
     */
    async _loadTreeRoots() {
        const falseGroup = this.root.groups.find((group) => group.value === false);
        if (falseGroup && falseGroup.list) {
            await falseGroup.list.load();
        }
    }

    /** Map parent record id -> its flat Group (for header name/count/fold state). */
    get treeParentMap() {
        const map = new Map();
        for (const group of this.root.groups) {
            if (group.value !== false) {
                map.set(group.value, group);
            }
        }
        return map;
    }

    /** Root records (parent_id === false), the top level of the tree. */
    get treeRoots() {
        const falseGroup = this.root.groups.find((group) => group.value === false);
        return falseGroup ? falseGroup.list.records : [];
    }

    /**
     * The visible tree flattened in pre-order: one entry per rendered row.
     * Rendering a flat sibling list (instead of a recursive t-call tree) keeps
     * Owl's block reconciliation happy when leaf rows mount field components.
     * `group` is set for rows that are also parent groups (group headers),
     * otherwise null (leaf record rows). Collapsed groups stop the descent.
     */
    get treeRows() {
        const parentMap = this.treeParentMap;
        const rows = [];
        const addNode = (record, depth, groupId) => {
            const group = parentMap.get(record.resId);
            rows.push({ key: record.resId, record, group, depth, groupId });
            if (group && !group.isFolded) {
                for (const child of group.list.records) {
                    addNode(child, depth + 1, group.id);
                }
            }
        };
        for (const record of this.treeRoots) {
            addNode(record, 0, false);
        }
        return rows;
    }
}
