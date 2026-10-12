import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const NODE_W = 160;
const NODE_H = 44;
const GAP_X = 80;
const GAP_Y = 32;
const PAD = 24;

function stateClass(state) {
    if (state === "1_done") {
        return "o_dep_node o_dep_done";
    }
    if (state === "1_canceled") {
        return "o_dep_node o_dep_canceled";
    }
    return "o_dep_node o_dep_open";
}

/**
 * Longest-path layering over a DAG (Kahn's topological sort + depth propagation),
 * then a left-to-right grid. ``depend_on_ids`` is guaranteed acyclic by
 * ``_check_no_cyclic_dependencies``, so this always terminates cleanly.
 */
function layeredLayout(nodes, edges) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const adj = new Map(nodes.map((n) => [n.id, []]));
    const indeg = new Map(nodes.map((n) => [n.id, 0]));
    for (const e of edges) {
        if (byId.has(e.source) && byId.has(e.target)) {
            adj.get(e.source).push(e.target);
            indeg.set(e.target, indeg.get(e.target) + 1);
        }
    }

    const queue = [...indeg].filter(([, d]) => d === 0).map(([id]) => id);
    const layer = new Map();
    while (queue.length) {
        const u = queue.shift();
        const lu = layer.get(u) || 0;
        for (const v of adj.get(u)) {
            layer.set(v, Math.max(layer.get(v) || 0, lu + 1));
            indeg.set(v, indeg.get(v) - 1);
            if (indeg.get(v) === 0) {
                queue.push(v);
            }
        }
    }

    const byLayer = new Map();
    for (const n of nodes) {
        const l = layer.get(n.id) || 0;
        if (!byLayer.has(l)) {
            byLayer.set(l, []);
        }
        byLayer.get(l).push(n);
    }

    const positioned = [];
    for (const l of [...byLayer.keys()].sort((a, b) => a - b)) {
        byLayer.get(l)
            .sort((a, b) => a.id - b.id)
            .forEach((n, i) => {
                positioned.push({
                    ...n,
                    x: PAD + l * (NODE_W + GAP_X),
                    y: PAD + i * (NODE_H + GAP_Y),
                    className: stateClass(n.state),
                });
            });
    }

    const pos = new Map(positioned.map((n) => [n.id, n]));
    const lines = edges
        .filter((e) => pos.has(e.source) && pos.has(e.target))
        .map((e) => {
            const s = pos.get(e.source);
            const t = pos.get(e.target);
            return {
                key: `${e.source}-${e.target}`,
                x1: s.x + NODE_W,
                y1: s.y + NODE_H / 2,
                x2: t.x,
                y2: t.y + NODE_H / 2,
            };
        });

    const width = positioned.reduce((w, n) => Math.max(w, n.x + NODE_W), 0) + PAD;
    const height = positioned.reduce((h, n) => Math.max(h, n.y + NODE_H), 0) + PAD;
    return { nodes: positioned, edges: lines, width, height };
}

export class TaskDependencyGraph extends Component {
    static template = "project_task_dependency.TaskDependencyGraph";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            nodes: [],
            edges: [],
            width: 0,
            height: 0,
            loading: true,
            error: null,
        });

        onWillStart(async () => {
            const projectId = this.props.action.context?.active_id;
            try {
                const data = await this.orm.call(
                    "project.task",
                    "get_dependency_graph_data",
                    [projectId]
                );
                Object.assign(this.state, layeredLayout(data.nodes, data.edges), {
                    loading: false,
                });
            } catch (err) {
                this.state.error = err.message || String(err);
                this.state.loading = false;
            }
        });
    }

    openTask(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("task_dependency_graph", TaskDependencyGraph);
