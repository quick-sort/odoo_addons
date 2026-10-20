/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { Component, onWillStart, useState, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { exprToBoolean } from "@web/core/utils/strings";
import { user } from "@web/core/user";
import { GanttRenderer } from "./gantt_renderer";

export class GanttController extends Component {
    static template = "web_gantt.GanttController";
    static components = { Layout, GanttRenderer };

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            scale: 'month',
            groupBy: this.props.groupBy?.[0] || 'project_id',
            ganttData: [],
            isLoading: false,
            editable: !this.props.readonly,
            hasCenteredToday: false,
            hasLoadedOnce: false,
        });

        onWillStart(async () => {
            await this.loadGanttData();
            if (!this.props.readonly) {
                this.state.editable = await user.checkAccessRight(this.props.resModel, "write");
            }
        });
        onWillUpdateProps(async (nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain) ||
                nextProps.groupBy !== this.props.groupBy) {
                await this.loadGanttData(nextProps);
            }
        });
    }

    get className() {
        return this.props.className;
    }

    async loadGanttData(props = this.props) {
        // Only show the spinner (which unmounts the renderer via t-if) on the
        // first load, when there is nothing to display yet. On reloads we keep
        // the renderer mounted with the previous data so scroll/zoom survive
        // and the canvas just redraws in place.
        const firstLoad = !this.state.hasLoadedOnce;
        if (firstLoad) {
            this.state.isLoading = true;
        }
        try {
            this.state.ganttData = await this.orm.call(
                props.resModel,
                'get_gantt_data',
                [],
                {
                    domain: props.domain || [],
                    group_by: this.state.groupBy
                }
            );
            this.state.hasLoadedOnce = true;
            // After first successful load, center on today once
            if (!this.state.hasCenteredToday) {
                window.dispatchEvent(new CustomEvent('gantt-navigate', { detail: { type: 'today' } }));
                this.state.hasCenteredToday = true;
            }
        } catch (error) {
            this.notification.add("Failed to load Gantt data", { type: "danger" });
            console.error("Gantt data load error:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    async onTaskUpdated(ev) {
        const { taskId, startDate, endDate } = ev.detail;
        try {
            // Format dates properly for Odoo
            const formatDateForOdoo = (date) => {
                if (!date) return false;
                if (date instanceof Date) {
                    return date.toISOString().replace('Z', '').replace('T', ' ');
                }
                return date;
            };

            const updateData = {
                [this.props.archInfo?.dateStart]: formatDateForOdoo(startDate),
                [this.props.archInfo?.dateStop]: formatDateForOdoo(endDate),
            };

            await this.orm.write(this.props.resModel, [taskId], updateData);
            this.notification.add("Task updated successfully", { type: "success" });
            // Reload so that any cascade from project_task_plan (auto-scheduling
            // of dependent tasks) is reflected too; the renderer stays mounted
            // across this reload, so no spinner flash / scroll reset.
            await this.loadGanttData();
        } catch (error) {
            this.notification.add("Failed to update task", { type: "danger" });
            console.error("Task update error:", error);
            await this.loadGanttData(); // Reload to revert changes on error
        }
    }

    onTaskClicked(ev) {
        const { taskId } = ev.detail;
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: this.props.resModel,
            res_id: taskId,
            views: [[false, 'form']],
            target: 'new',
        }, {
            onClose: async () => {
                await this.loadGanttData();
            }
        });
    }

    onScaleChange(scale) {
        this.state.scale = scale;
    }

    navigate(type) {
        // Dispatch a window-level event so the renderer can listen regardless of DOM structure
        const event = new CustomEvent('gantt-navigate', { detail: { type } });
        window.dispatchEvent(event);
    }

    async onGroupByChange(ev) {
        this.state.groupBy = ev.target.value;
        await this.loadGanttData();
    }

    createTask() {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: this.props.resModel,
            views: [[false, 'form']],
            target: 'new',
            context: {
                ['default_' + this.props.archInfo?.dateStart]: new Date().toISOString().replace('Z','').replace('T',' ').split('.')[0],
            },
        }, {
            onClose: async () => {
                await this.loadGanttData();
            }
        });
    }

    async refresh() {
        await this.loadGanttData();
    }

    toggleEditable() {
        if (this.props.readonly) {
            return;
        }
        this.state.editable = !this.state.editable;
    }

    exportToCSV() {
        const data = this.state.ganttData;
        if (!data || data.length === 0) {
            this.notification.add("No data to export", { type: "warning" });
            return;
        }

        let csv = "Group,Task Name,Start Date,End Date,Progress,Duration (Days)\n";
        data.forEach(group => {
            group.tasks.forEach(task => {
                const start = new Date(task.start_date);
                const end = task.end_date ? new Date(task.end_date) : new Date(start.getTime() + 86400000);
                const duration = ((end - start) / 86400000).toFixed(1);
                csv += `"${group.name}","${task.name}","${start.toLocaleDateString()}","${end.toLocaleDateString()}",${task.progress},${duration}\n`;
            });
        });

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `gantt_chart_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        window.URL.revokeObjectURL(url);
    }
}

export class GanttView extends Component {
    static template = "web_gantt.GanttView";
    static components = { Layout, GanttController };

    setup() {
        this.state = useState({
            groupBy: this.props.context?.group_by?.[0] || 'project_id',
        });
    }

    getControllerProps() {
        return {
            resModel: this.props.resModel,
            domain: this.props.domain,
            context: this.props.context,
            groupBy: this.state.groupBy,
            dateStart: this.props.archInfo?.dateStart || "date_start",
            dateStop: this.props.archInfo?.dateStop || "date_stop",
            readonly: this.props.readonly,
        };
    }
}

export const ganttView = {
    type: "gantt",
    display_name: "Gantt",
    icon: "fa-tasks",
    multiRecord: true,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    Controller: GanttController,
    Component: GanttView,

    props: (genericProps) => {
        const { arch } = genericProps;
        const editable = exprToBoolean(arch.getAttribute("edit"), true);
        return {
            ...genericProps,
            Model: undefined,
            Renderer: undefined,
            buttonTemplate: arch.getAttribute("button_template") || undefined,
            readonly: genericProps.readonly || !editable,
            archInfo: {
                fieldNames: [],
                dateStart: arch.getAttribute("date_start") || "date_start",
                dateStop: arch.getAttribute("date_stop") || "date_stop",
            },
        };
    },
};

registry.category("views").add("gantt", ganttView);
