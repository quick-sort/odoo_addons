/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState, onWillUpdateProps } from "@odoo/owl";

// Odoo's kanban/tag palette ($o-colors), indexed like the integer `color`
// field used by project.task. Index 0 means "no explicit color".
const TASK_COLOR_PALETTE = [
    null,
    "#ee2d2d", "#dc8534", "#e8bb1d", "#5794dd", "#9f628f", "#db8865",
    "#41a9a2", "#304be0", "#ee2f8a", "#61c36e", "#9872e6",
];

export class GanttRenderer extends Component {
    static template = "web_gantt.GanttRenderer";
    static props = {
        data: { type: Array },
        markers: { type: Array, optional: true },
        scale: { type: String },
        editable: { type: Boolean, optional: true },
        showDependencies: { type: Boolean, optional: true },
    };

    setup() {
        this.root = useRef("root");
        this.canvasRef = useRef("ganttCanvas");
        this.containerRef = useRef("ganttContainer");
        
        this.state = useState({
            scrollX: 0,
            scrollY: 0,
            draggedTask: null,
            isPanning: false,
            panStartX: 0,
            tooltip: { visible: false, content: '', x: 0, y: 0 },
            hoveredTask: null,
            zoom: 1.0,
            scrollbarDragging: false,
            collapsedIds: {},
        });

        // Base dimensions
        this.baseCellWidth = 40;
        this.baseCellHeight = 32;
        this.headerHeight = 80;
        this.sidebarWidth = 250;
        this.minSidebarWidth = 120;
        this.maxSidebarWidth = 600;
        this.scrollbarWidth = 10;
        this.minCellWidth = 20;
        this.maxCellWidth = 100;
        // Active sidebar resize gesture: {startClientX, startWidth} or null.
        this._sidebarResize = null;
        // Set when a resize gesture ends, to swallow the trailing click.
        this._suppressClick = false;
        this.scrollbarMetrics = null;
        this.scrollbarRect = null;
        this._scrollbarDragOffset = 0;
        this._rowsCache = null;
        this._markerHitAreas = [];
        this._lastScale = this.props.scale;

        this.animationFrame = null;
        this.lastDrawTime = 0;
        this.drawDelay = 16; // ~60fps

        onMounted(() => {
            this.setupCanvas();
            this.drawGantt();
            window.addEventListener('resize', this.handleResize.bind(this));
            // Listen for navigation commands globally
            this._navigateHandler = (e) => this.handleNavigate(e.detail);
            window.addEventListener('gantt-navigate', this._navigateHandler);
            // Center view on today initially for better UX
            this.centerOnToday();
            // Keyboard navigation
            this._keyHandler = (e) => this.handleKey(e);
            window.addEventListener('keydown', this._keyHandler);
            // Export the whole chart as an image
            this._exportHandler = () => this.exportImage();
            window.addEventListener('gantt-export-image', this._exportHandler);
        });

        onWillUnmount(() => {
            window.removeEventListener('resize', this.handleResize.bind(this));
            if (this.animationFrame) {
                cancelAnimationFrame(this.animationFrame);
            }
            if (this._navigateHandler) {
                window.removeEventListener('gantt-navigate', this._navigateHandler);
            }
            if (this._keyHandler) {
                window.removeEventListener('keydown', this._keyHandler);
            }
            if (this._exportHandler) {
                window.removeEventListener('gantt-export-image', this._exportHandler);
            }
        });

        onWillUpdateProps((nextProps) => {
            // onWillUpdateProps fires before the new props (scale/data) are
            // committed, so drawing here would use stale values. Defer one
            // frame and re-clamp the scroll so the redraw sees the new cell
            // width and content extent (otherwise a scale switch leaves the
            // canvas blank until the next wheel/pan event).
            const scaleChanged = nextProps.scale !== this._lastScale;
            if (this.animationFrame) {
                cancelAnimationFrame(this.animationFrame);
            }
            this.animationFrame = requestAnimationFrame(() => {
                this.animationFrame = null;
                if (scaleChanged) {
                    // A scale switch changes the cell width and thus where
                    // "today" lands, so recenter on it instead of preserving
                    // the old scroll offset.
                    this.centerOnToday();
                } else {
                    this.clampScrollIntoView();
                    this.drawGantt();
                }
                this.lastDrawTime = Date.now();
            });
            this._lastScale = nextProps.scale;
        });
    }
    formatDateLocal(date) {
        const pad = (n) => String(n).padStart(2, '0');
        const d = date instanceof Date ? date : new Date(date);
        return (
            d.getFullYear() + '-' +
            pad(d.getMonth() + 1) + '-' +
            pad(d.getDate()) + ' ' +
            pad(d.getHours()) + ':' +
            pad(d.getMinutes()) + ':' +
            pad(d.getSeconds())
        );
    }

    getTaskEndDate(task) {
        if (task.end_date) {
            return new Date(task.end_date);
        }
        const start = new Date(task.start_date);
        return new Date(start.getTime() + 86400000); // default: start + 1 day
    }

    addMonths(date, months) {
        const result = new Date(date);
        const day = result.getDate();
        result.setDate(1);
        result.setMonth(result.getMonth() + months);
        const daysInMonth = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
        result.setDate(Math.min(day, daysInMonth));
        return result;
    }

    get cellWidth() {
        // Adjust base width per scale for better zooming behavior
        const scale = this.props.scale || 'day';
        const scaleFactor = (
            scale === 'day' ? 1.0 :
            scale === 'week' ? 1.2 :
            scale === 'month' ? 0.6 :
            0.8 // quarter
        );
        const width = this.baseCellWidth * scaleFactor * this.state.zoom;
        return Math.max(this.minCellWidth, Math.min(this.maxCellWidth, width));
    }

    get cellHeight() {
        return this.baseCellHeight;
    }

    getRows(data) {
        const collapsedKey = Object.keys(this.state.collapsedIds || {}).sort().join(',');
        if (this._rowsCache && this._rowsCache.data === data && this._rowsCache.collapsedKey === collapsedKey) {
            return this._rowsCache.rows;
        }
        const rows = [];
        (data || []).forEach(group => {
            rows.push({ type: 'group', group });
            const tasks = group.tasks || [];
            const ids = new Set(tasks.map(t => t.id));
            const parentIds = new Set(
                tasks.filter(t => t.parent_id && ids.has(t.parent_id)).map(t => t.parent_id)
            );
            // Tasks arrive in DFS pre-order, so a collapsed task can hide every
            // following task whose depth is greater until a sibling appears.
            let hiddenBelow = null;
            tasks.forEach(task => {
                const depth = task.depth || 0;
                if (hiddenBelow !== null && depth > hiddenBelow) {
                    return;
                }
                hiddenBelow = null;
                rows.push({ type: 'task', group, task, hasChildren: parentIds.has(task.id) });
                if (this.state.collapsedIds[task.id]) {
                    hiddenBelow = depth;
                }
            });
        });
        this._rowsCache = { data, collapsedKey, rows };
        return rows;
    }

    getTotalUnits(dates) {
        const scale = this.props.scale || 'day';
        const days = Math.ceil((dates.end - dates.start) / 86400000);
        if (scale === 'week') {
            return Math.ceil(days / 7);
        }
        if (scale === 'day') {
            return Math.max(1, days);
        }
        const months = (dates.end.getFullYear() - dates.start.getFullYear()) * 12
            + (dates.end.getMonth() - dates.start.getMonth()) + 1;
        return scale === 'quarter' ? Math.max(1, Math.ceil(months / 3)) : Math.max(1, months);
    }

    getRowAtY(y) {
        const rows = this.getRows(this.props.data);
        const index = Math.floor((y - this.headerHeight + this.state.scrollY) / this.cellHeight);
        if (index < 0 || index >= rows.length) {
            return null;
        }
        return rows[index];
    }

    getMaxScrollY(rect) {
        const rows = this.getRows(this.props.data);
        const viewportHeight = rect.height - this.headerHeight;
        return Math.max(0, rows.length * this.cellHeight - viewportHeight);
    }

    setupCanvas() {
        const canvas = this.canvasRef.el;
        const container = this.containerRef.el;
        if (!canvas || !container) return;

        const rect = container.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';
        
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
    }

    handleResize() {
        this.setupCanvas();
        this.clampScrollIntoView();
        this.scheduleRedraw();
    }

    scheduleRedraw() {
        const now = Date.now();
        if (now - this.lastDrawTime >= this.drawDelay) {
            this.drawGantt();
            this.lastDrawTime = now;
        } else if (!this.animationFrame) {
            this.animationFrame = requestAnimationFrame(() => {
                this.animationFrame = null;
                this.drawGantt();
                this.lastDrawTime = Date.now();
            });
        }
    }

    drawGantt() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const data = this.props.data;
        const rect = canvas.getBoundingClientRect();

        ctx.clearRect(0, 0, rect.width, rect.height);
        this.scrollbarMetrics = null;
        this.scrollbarRect = null;
        this._markerHitAreas = [];

        if (!data || data.length === 0) {
            this.drawEmptyState(ctx, rect);
            return;
        }

        const dates = this.calculateDateRange(data);
        if (!dates.start || !dates.end) {
            this.drawEmptyState(ctx, rect);
            return;
        }

        this.drawLayers(ctx, rect, dates, data);
        this.drawScrollbar(ctx, rect);
    }

    drawLayers(ctx, rect, dates, data) {
        // Draw in layers for better visual hierarchy
        this.drawGrid(ctx, dates, data, rect);
        this.drawTodayMarker(ctx, dates, rect);
        this.drawTasks(ctx, data, dates, rect);
        this.drawDependencies(ctx, data, dates, rect);
        this.drawHeader(ctx, dates, rect);
        this.drawMarkers(ctx, dates, rect);
        this.drawSidebar(ctx, data, rect);
    }

    async exportImage() {
        const data = this.props.data || [];
        const rows = this.getRows(data);
        const dates = this.calculateExportDateRange(data);
        if (!dates || !rows.length) {
            return;
        }

        const prevScrollX = this.state.scrollX;
        const prevScrollY = this.state.scrollY;
        const prevZoom = this.state.zoom;
        const prevHover = this.state.hoveredTask;
        this.state.scrollX = 0;
        this.state.scrollY = 0;
        this.state.hoveredTask = null;
        this.state.tooltip.visible = false;

        try {
            let cellWidth = this.cellWidth;
            const totalUnits = this.getTotalUnits(dates);
            const maxWidth = 16000;
            if (totalUnits * cellWidth > maxWidth - this.sidebarWidth) {
                // Very long timelines: shrink cells so the PNG stays within
                // safe canvas dimensions.
                this.state.zoom = this.state.zoom * (maxWidth - this.sidebarWidth) / (totalUnits * cellWidth);
                cellWidth = this.cellWidth;
            }
            const width = Math.ceil(this.sidebarWidth + totalUnits * cellWidth + 1);
            const height = Math.ceil(this.headerHeight + rows.length * this.cellHeight + 1);
            const pixelScale = Math.min(2, maxWidth / width, maxWidth / height);

            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.ceil(width * pixelScale));
            canvas.height = Math.max(1, Math.ceil(height * pixelScale));
            const ctx = canvas.getContext('2d');
            ctx.scale(pixelScale, pixelScale);
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, width, height);
            this.drawLayers(ctx, { width, height }, dates, data);

            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
            if (!blob) {
                return;
            }
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `gantt_chart_${new Date().toISOString().split('T')[0]}.png`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } finally {
            this.state.scrollX = prevScrollX;
            this.state.scrollY = prevScrollY;
            this.state.zoom = prevZoom;
            this.state.hoveredTask = prevHover;
            this._markerHitAreas = [];
            this.scheduleRedraw();
        }
    }

    getMaxScrollX(rect, dates) {
        // total content width minus viewport
        const contentWidth = this.sidebarWidth + this.getTotalUnits(dates) * this.cellWidth;
        const viewportWidth = rect.width;
        return Math.max(0, contentWidth - viewportWidth);
    }

    clampScrollIntoView() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const data = this.props.data || [];
        const dates = this.calculateDateRange(data);
        const maxX = this.getMaxScrollX(rect, dates);
        const maxY = this.getMaxScrollY(rect);
        this.state.scrollX = Math.max(0, Math.min(this.state.scrollX, maxX));
        this.state.scrollY = Math.max(0, Math.min(this.state.scrollY, maxY));
    }

    centerOnToday() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const data = this.props.data || [];
        const dates = this.calculateDateRange(data);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        // Use the same dateToX calculation to ensure consistency
        const xToday = this.dateToX(today, dates) + this.state.scrollX;
        const centerX = this.sidebarWidth + (rect.width - this.sidebarWidth) / 2;
        this.state.scrollX = Math.max(0, xToday - centerX);
        this.clampScrollIntoView();
        this.scheduleRedraw();
    }

    drawEmptyState(ctx, rect) {
        ctx.font = '16px Arial';
        ctx.fillStyle = '#aaa';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No tasks with start and end dates to display.', rect.width / 2, rect.height / 2);
    }

    calculateDateRange(data) {
        let minDate, maxDate;
        
        data.forEach(g => g.tasks.forEach(t => {
            const start = new Date(t.start_date);
            const end = this.getTaskEndDate(t);
            if (!minDate || start < minDate) minDate = start;
            if (!maxDate || end > maxDate) maxDate = end;
        }));

        this.getMarkers().forEach(marker => {
            const date = this.parseMarkerDate(marker.date);
            if (!date) return;
            if (!minDate || date < minDate) minDate = date;
            if (!maxDate || date > maxDate) maxDate = date;
        });

        if (!minDate || !maxDate) {
            // If no tasks, show current month with some padding
            const today = new Date();
            minDate = new Date(today.getFullYear(), today.getMonth() - 6, 1);
            maxDate = new Date(today.getFullYear(), today.getMonth() + 18, 0);
            return { start: minDate, end: maxDate };
        }

        // Add much more padding to date range for better navigation
        minDate = new Date(minDate.getFullYear(), minDate.getMonth() - 12, 1);
        maxDate = new Date(maxDate.getFullYear(), maxDate.getMonth() + 24, 0);

        return { start: minDate, end: maxDate };
    }

    calculateExportDateRange(data) {
        let minDate, maxDate;
        (data || []).forEach(g => (g.tasks || []).forEach(t => {
            const start = new Date(t.start_date);
            const end = this.getTaskEndDate(t);
            if (!minDate || start < minDate) minDate = start;
            if (!maxDate || end > maxDate) maxDate = end;
        }));
        this.getMarkers().forEach(marker => {
            const date = this.parseMarkerDate(marker.date);
            if (!date) return;
            if (!minDate || date < minDate) minDate = date;
            if (!maxDate || date > maxDate) maxDate = date;
        });
        if (!minDate || !maxDate) {
            return null;
        }

        // Snap to whole scale units so the exported image has clean edges.
        const scale = this.props.scale || 'day';
        let start, end;
        if (scale === 'week') {
            start = new Date(minDate);
            start.setDate(start.getDate() - start.getDay());
            start.setHours(0, 0, 0, 0);
            end = new Date(maxDate);
            end.setDate(end.getDate() - end.getDay() + 6);
            end.setHours(23, 59, 59, 999);
        } else if (scale === 'day') {
            start = new Date(minDate.getFullYear(), minDate.getMonth(), 1);
            end = new Date(maxDate.getFullYear(), maxDate.getMonth() + 1, 0, 23, 59, 59, 999);
        } else if (scale === 'quarter') {
            const startQuarterMonth = Math.floor(minDate.getMonth() / 3) * 3;
            const endQuarterMonth = Math.floor(maxDate.getMonth() / 3) * 3;
            start = new Date(minDate.getFullYear(), startQuarterMonth, 1);
            end = new Date(maxDate.getFullYear(), endQuarterMonth + 3, 0, 23, 59, 59, 999);
        } else {
            start = new Date(minDate.getFullYear(), 0, 1);
            end = new Date(maxDate.getFullYear(), 11, 31, 23, 59, 59, 999);
        }
        return { start, end };
    }

    // X positions of the visible date cells for the current scale. Used for
    // grid lines and header separators so both stay aligned.
    getScaleBoundaries(dates) {
        const scale = this.props.scale || 'day';
        const boundaries = [];
        const push = (date) => {
            boundaries.push(this.dateToX(date, dates));
        };
        if (scale === 'day') {
            const current = new Date(
                dates.start.getFullYear(),
                dates.start.getMonth(),
                dates.start.getDate()
            );
            while (current <= dates.end) {
                push(current);
                current.setDate(current.getDate() + 1);
            }
        } else if (scale === 'week') {
            const current = new Date(dates.start);
            current.setDate(current.getDate() - current.getDay());
            while (current <= dates.end) {
                push(current);
                current.setDate(current.getDate() + 7);
            }
        } else if (scale === 'quarter') {
            const current = new Date(
                dates.start.getFullYear(),
                Math.floor(dates.start.getMonth() / 3) * 3,
                1
            );
            while (current <= dates.end) {
                push(current);
                current.setMonth(current.getMonth() + 3);
            }
        } else {
            const current = new Date(dates.start.getFullYear(), dates.start.getMonth(), 1);
            while (current <= dates.end) {
                push(current);
                current.setMonth(current.getMonth() + 1);
            }
        }
        return boundaries;
    }

    drawGrid(ctx, dates, data, rect) {
        // Vertical separators between date cells.
        ctx.strokeStyle = '#ced4da';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const x of this.getScaleBoundaries(dates)) {
            if (x >= this.sidebarWidth && x <= rect.width) {
                ctx.moveTo(x, this.headerHeight);
                ctx.lineTo(x, rect.height);
            }
        }
        ctx.stroke();

        ctx.strokeStyle = '#e9e9e9';

        // Horizontal grid lines (rows: group headers + tasks)
        const rows = this.getRows(data);
        for (let i = 0; i <= rows.length; i++) {
            const y = this.headerHeight + i * this.cellHeight - this.state.scrollY;
            if (y >= this.headerHeight && y <= rect.height) {
                ctx.beginPath();
                ctx.moveTo(this.sidebarWidth, y);
                ctx.lineTo(rect.width, y);
                ctx.stroke();
            }
        }
    }

    drawTodayMarker(ctx, dates, rect) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        
        if (today >= dates.start && today <= dates.end) {
            const x = this.dateToX(today, dates);
            if (x >= this.sidebarWidth && x <= rect.width) {
                ctx.save();
                ctx.strokeStyle = '#e74c3c';
                ctx.lineWidth = 2;
                ctx.setLineDash([5, 5]);
                ctx.beginPath();
                ctx.moveTo(x, this.headerHeight);
                ctx.lineTo(x, rect.height);
                ctx.stroke();
                ctx.restore();
            }
        }
    }

    getMarkers() {
        return Array.isArray(this.props.markers) ? this.props.markers : [];
    }

    parseMarkerDate(value) {
        if (!value) return null;
        if (value instanceof Date) {
            return isNaN(value.getTime()) ? null : value;
        }
        const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
        if (dateOnly) {
            // Date-only strings must be built in local time: `new Date('YYYY-MM-DD')`
            // is parsed as UTC and would shift the line by one day in negative offsets.
            return new Date(
                Number(dateOnly[1]),
                Number(dateOnly[2]) - 1,
                Number(dateOnly[3])
            );
        }
        const parsed = new Date(value);
        return isNaN(parsed.getTime()) ? null : parsed;
    }

    resolveMarkerColor(marker) {
        const color = marker && marker.color;
        if (typeof color === 'string' &&
            /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(color)) {
            return color;
        }
        // Invalid colors are silently ignored by canvas, so validate first.
        return '#71639e';
    }

    formatMarkerTooltip(marker) {
        const date = this.parseMarkerDate(marker.date);
        let text = marker.label || '';
        if (date) {
            text += (text ? '\n' : '') + date.toLocaleDateString();
        }
        if (marker.description) {
            text += (text ? '\n' : '') + marker.description;
        }
        return text;
    }

    getMarkerAt(x, y) {
        if (y < this.headerHeight || x < this.sidebarWidth) {
            return null;
        }
        // Label pills take precedence over the thin vertical line.
        for (const area of this._markerHitAreas) {
            const rect = area.labelRect;
            if (rect && x >= rect.x && x <= rect.x + rect.width &&
                y >= rect.y && y <= rect.y + rect.height) {
                return area.marker;
            }
        }
        for (const area of this._markerHitAreas) {
            if (Math.abs(x - area.x) <= 4) {
                return area.marker;
            }
        }
        return null;
    }

    drawMarkers(ctx, dates, rect) {
        this._markerHitAreas = [];
        const entries = [];
        for (const marker of this.getMarkers()) {
            const date = this.parseMarkerDate(marker.date);
            if (!date || date < dates.start || date > dates.end) {
                continue;
            }
            const x = this.dateToX(date, dates);
            if (x < this.sidebarWidth - 4 || x > rect.width) {
                continue;
            }
            entries.push({ marker, x });
        }
        if (!entries.length) {
            return;
        }
        entries.sort((a, b) => a.x - b.x);

        ctx.save();
        ctx.beginPath();
        ctx.rect(
            this.sidebarWidth,
            this.headerHeight,
            rect.width - this.sidebarWidth,
            rect.height - this.headerHeight
        );
        ctx.clip();

        for (const entry of entries) {
            ctx.save();
            ctx.strokeStyle = this.resolveMarkerColor(entry.marker);
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(entry.x, this.headerHeight);
            ctx.lineTo(entry.x, rect.height);
            ctx.stroke();
            ctx.restore();

            entry.area = { x: entry.x, marker: entry.marker };
            this._markerHitAreas.push(entry.area);
        }

        // Labels: two lanes, placed to the right of the line; skip a label
        // when both lanes are already occupied at that x.
        const labelHeight = 16;
        const laneY = [this.headerHeight + 2, this.headerHeight + 20];
        const laneRight = [this.sidebarWidth, this.sidebarWidth];
        ctx.font = '11px Arial';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        for (const entry of entries) {
            if (!entry.marker.label) {
                continue;
            }
            const text = this.truncateText(ctx, String(entry.marker.label), 180);
            const width = ctx.measureText(text).width + 12;
            const rightLimit = rect.width - this.scrollbarWidth - 2;
            let left = entry.x + 3;
            if (left + width > rightLimit) {
                left = entry.x - width - 3;
            }
            left = Math.max(this.sidebarWidth + 2, Math.min(left, rightLimit - width));
            let lane = -1;
            for (let i = 0; i < laneY.length; i++) {
                if (left >= laneRight[i] + 4) {
                    lane = i;
                    break;
                }
            }
            if (lane < 0) {
                continue;
            }
            ctx.fillStyle = this.resolveMarkerColor(entry.marker);
            this.roundRect(ctx, left, laneY[lane], width, labelHeight, 4, true, false);
            ctx.fillStyle = '#ffffff';
            ctx.fillText(text, left + 6, laneY[lane] + labelHeight / 2);
            laneRight[lane] = left + width;
            entry.area.labelRect = {
                x: left,
                y: laneY[lane],
                width,
                height: labelHeight,
            };
        }

        ctx.restore();
    }

    // Upper header row groups: months for day/week scales, years for
    // month/quarter scales. Each group is drawn as one merged cell.
    getHeaderGroups(dates) {
        const scale = this.props.scale || 'day';
        const groups = [];
        if (scale === 'month' || scale === 'quarter') {
            let current = new Date(dates.start.getFullYear(), 0, 1);
            while (current <= dates.end) {
                const next = new Date(current.getFullYear() + 1, 0, 1);
                groups.push({
                    start: current,
                    end: next,
                    label: String(current.getFullYear()),
                });
                current = next;
            }
        } else {
            let current = new Date(dates.start.getFullYear(), dates.start.getMonth(), 1);
            while (current <= dates.end) {
                const next = new Date(current.getFullYear(), current.getMonth() + 1, 1);
                groups.push({
                    start: current,
                    end: next,
                    label: current.toLocaleDateString('en-US', {
                        month: 'short',
                        year: 'numeric',
                    }),
                });
                current = next;
            }
        }
        return groups;
    }

    drawHeader(ctx, dates, rect) {
        // Background
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, 0, rect.width, this.headerHeight);

        ctx.strokeStyle = '#dee2e6';
        ctx.lineWidth = 1;
        ctx.strokeRect(0, 0, rect.width, this.headerHeight);

        ctx.save();
        ctx.beginPath();
        ctx.rect(this.sidebarWidth, 0, rect.width - this.sidebarWidth, this.headerHeight);
        ctx.clip();

        const splitY = Math.round(this.headerHeight / 2);
        const groups = this.getHeaderGroups(dates);

        // Upper row: merged month/year cells, so only the group boundaries
        // are drawn; the horizontal line separates it from the date cells.
        ctx.strokeStyle = '#ced4da';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (const group of groups) {
            const x = this.dateToX(group.start, dates);
            if (x >= this.sidebarWidth && x <= rect.width) {
                ctx.moveTo(x, 0);
                ctx.lineTo(x, splitY);
            }
        }
        ctx.moveTo(this.sidebarWidth, splitY);
        ctx.lineTo(rect.width, splitY);
        ctx.stroke();

        // Lower row: one separator per date cell.
        ctx.beginPath();
        for (const x of this.getScaleBoundaries(dates)) {
            if (x >= this.sidebarWidth && x <= rect.width) {
                ctx.moveTo(x, splitY);
                ctx.lineTo(x, this.headerHeight);
            }
        }
        ctx.stroke();

        // Merged upper-row labels, centered in the visible part of each group.
        ctx.fillStyle = '#495057';
        ctx.font = 'bold 13px Arial';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';
        for (const group of groups) {
            const startX = this.dateToX(group.start, dates);
            const endX = this.dateToX(group.end, dates);
            const left = Math.max(this.sidebarWidth, startX);
            const right = Math.min(rect.width, endX);
            if (right <= left) {
                continue;
            }
            const textWidth = ctx.measureText(group.label).width;
            if (right - left < textWidth + 8) {
                continue;
            }
            ctx.fillText(group.label, (left + right) / 2, splitY / 2);
        }

        // Lower-row labels for the current scale, centered in each cell
        // (both horizontally and within the lower header band).
        ctx.fillStyle = '#6c757d';
        ctx.font = '11px Arial';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';
        const labelY = splitY + (this.headerHeight - splitY) / 2;
        const centerOf = (cellX) => cellX + this.cellWidth / 2;
        const scale = this.props.scale || 'day';
        if (scale === 'week') {
            let weekStart = new Date(dates.start);
            weekStart.setDate(weekStart.getDate() - weekStart.getDay());
            while (weekStart <= dates.end) {
                const weekX = this.dateToX(weekStart, dates);
                ctx.fillText(`W${this.getWeekNumber(weekStart)}`, centerOf(weekX), labelY);
                weekStart.setDate(weekStart.getDate() + 7);
            }
        } else if (scale === 'day') {
            let dayCounter = new Date(dates.start);
            const days = Math.ceil((dates.end - dates.start) / 86400000);
            for (let i = 0; i <= days; i++) {
                const dayX = this.dateToX(dayCounter, dates);
                ctx.fillText(dayCounter.getDate().toString(), centerOf(dayX), labelY);
                dayCounter.setDate(dayCounter.getDate() + 1);
            }
        } else if (scale === 'quarter') {
            let current = new Date(
                dates.start.getFullYear(),
                Math.floor(dates.start.getMonth() / 3) * 3,
                1
            );
            while (current <= dates.end) {
                const quarterX = this.dateToX(current, dates);
                if (quarterX >= this.sidebarWidth && quarterX <= rect.width) {
                    const quarter = Math.floor(current.getMonth() / 3) + 1;
                    ctx.fillText(`Q${quarter}`, centerOf(quarterX), labelY);
                }
                current.setMonth(current.getMonth() + 3);
            }
        } else if (scale === 'month') {
            let current = new Date(dates.start.getFullYear(), dates.start.getMonth(), 1);
            while (current <= dates.end) {
                const monthX = this.dateToX(current, dates);
                ctx.fillText(
                    current.toLocaleDateString('en-US', { month: 'short' }),
                    centerOf(monthX),
                    labelY
                );
                current.setMonth(current.getMonth() + 1);
            }
        }

        ctx.restore();
    }

    drawSidebar(ctx, data, rect) {
        // Background
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, this.headerHeight, this.sidebarWidth, rect.height - this.headerHeight);

        ctx.strokeStyle = '#dee2e6';
        ctx.strokeRect(0, 0, this.sidebarWidth, rect.height);

        ctx.save();
        ctx.beginPath();
        ctx.rect(0, this.headerHeight, this.sidebarWidth, rect.height - this.headerHeight);
        ctx.clip();

        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        const rows = this.getRows(data);

        rows.forEach((row, index) => {
            const y = this.headerHeight + index * this.cellHeight - this.state.scrollY;
            const rowBottom = y + this.cellHeight;
            if (rowBottom <= this.headerHeight || y >= rect.height) {
                return;
            }

            if (row.type === 'group') {
                ctx.fillStyle = 'rgba(0, 0, 0, 0.04)';
                ctx.fillRect(0, y, this.sidebarWidth, this.cellHeight);
                ctx.fillStyle = '#343a40';
                ctx.font = 'bold 12px Arial';
                const groupText = `${row.group.name} (${row.group.tasks.length})`;
                const truncated = this.truncateText(ctx, groupText, this.sidebarWidth - 16);
                ctx.fillText(truncated, 10, y + this.cellHeight / 2);
            } else {
                const task = row.task;
                const depth = task.depth || 0;
                const indent = Math.min(10 + depth * 14, 120);
                const dotRadius = 4;
                const centerY = y + this.cellHeight / 2;
                const dotX = row.hasChildren ? indent + 18 : indent + 6;
                row._caretRect = null;

                // tree connector
                ctx.strokeStyle = '#dee2e6';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(indent - 2, centerY);
                ctx.lineTo(dotX - dotRadius - 2, centerY);
                ctx.stroke();

                // collapse / expand caret
                if (row.hasChildren) {
                    const collapsed = !!this.state.collapsedIds[task.id];
                    ctx.fillStyle = '#6c757d';
                    ctx.beginPath();
                    if (collapsed) {
                        ctx.moveTo(indent + 1, centerY - 4);
                        ctx.lineTo(indent + 8, centerY);
                        ctx.lineTo(indent + 1, centerY + 4);
                    } else {
                        ctx.moveTo(indent, centerY - 3);
                        ctx.lineTo(indent + 8, centerY - 3);
                        ctx.lineTo(indent + 4, centerY + 3);
                    }
                    ctx.closePath();
                    ctx.fill();
                    row._caretRect = { x: indent - 3, y, width: 15, height: this.cellHeight };
                }

                // task color dot
                ctx.fillStyle = this.resolveTaskColor(task);
                ctx.beginPath();
                ctx.arc(dotX, centerY, dotRadius, 0, Math.PI * 2);
                ctx.fill();

                // task name + assignee
                const textX = dotX + dotRadius + 8;
                let nameMaxWidth = this.sidebarWidth - textX - 10;
                const assignees = task.assignees || [];
                if (assignees.length) {
                    ctx.font = '11px Arial';
                    const assigneeText = this.truncateText(
                        ctx,
                        assignees.join(', '),
                        Math.max(40, Math.min(110, this.sidebarWidth * 0.42))
                    );
                    const assigneeWidth = ctx.measureText(assigneeText).width;
                    ctx.fillStyle = '#868e96';
                    ctx.fillText(assigneeText, this.sidebarWidth - assigneeWidth - 8, centerY);
                    nameMaxWidth = this.sidebarWidth - textX - assigneeWidth - 20;
                }
                ctx.fillStyle = '#495057';
                ctx.font = '12px Arial';
                const truncated = this.truncateText(ctx, task.name, Math.max(20, nameMaxWidth));
                ctx.fillText(truncated, textX, centerY);
            }

            // row separator
            ctx.strokeStyle = '#e9ecef';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, rowBottom);
            ctx.lineTo(this.sidebarWidth, rowBottom);
            ctx.stroke();
        });

        ctx.restore();
    }

    drawTasks(ctx, data, dates, rect) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(this.sidebarWidth, this.headerHeight, rect.width - this.sidebarWidth, rect.height - this.headerHeight);
        ctx.clip();

        const rows = this.getRows(data);

        rows.forEach((row, index) => {
            if (row.type !== 'task') {
                return;
            }
            const task = row.task;
            const start = new Date(task.start_date);
            const end = this.getTaskEndDate(task);

            // If end time is exactly midnight (00:00:00), treat it as end of previous day
            if (end.getHours() === 0 && end.getMinutes() === 0 && end.getSeconds() === 0) {
                end.setDate(end.getDate() - 1);
                end.setHours(23, 59, 59, 999);
            }

            const startX = this.dateToX(start, dates);
            const endX = this.dateToX(end, dates);
            const width = Math.max(endX - startX, 5);
            const y = this.headerHeight + (index * this.cellHeight) + 4 - this.state.scrollY;
            const height = this.cellHeight - 8;

            if (y + this.cellHeight > this.headerHeight && y < rect.height) {
                const isHovered = this.state.hoveredTask?.id === task.id;
                const isDragged = this.state.draggedTask?.id === task.id;
                const taskRgb = this.hexToRgb(this.resolveTaskColor(task));
                const taskColor = this.colorToHex(taskRgb);
                const trackColor = this.colorToHex(this.lighten(taskRgb, 0.78));

                // Task bar shadow
                if (isHovered || isDragged) {
                    ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
                    ctx.shadowBlur = 10;
                    ctx.shadowOffsetY = 3;
                }

                if (isDragged) {
                    ctx.globalAlpha = 0.7;
                }

                // Unfinished track: light tint fill with a theme-color border so
                // the bar stays visible and the done/undone split is obvious.
                ctx.fillStyle = trackColor;
                ctx.strokeStyle = taskColor;
                ctx.lineWidth = 1;
                this.roundRect(ctx, startX, y, width, height, 6, true, true);

                ctx.shadowColor = 'transparent';
                ctx.shadowBlur = 0;
                ctx.shadowOffsetY = 0;

                // Completed portion: solid theme color.
                let progressWidth = 0;
                if (task.progress > 0) {
                    // progress may exceed 100 (hr_timesheet overtime); clamp the
                    // bar to the task width but keep the real value in tooltip/CSV.
                    progressWidth = (width - 4) * (Math.min(task.progress, 100) / 100);
                    ctx.fillStyle = taskColor;
                    this.roundRect(ctx, startX + 2, y + 2, progressWidth, height - 4, 4, true, false);
                }

                // Task name
                if (width > 40) {
                    ctx.fillStyle = progressWidth > 4 && this.colorLuminance(taskRgb) <= 0.6
                        ? '#ffffff'
                        : '#343a40';
                    ctx.font = isHovered ? 'bold 11px Arial' : '11px Arial';
                    ctx.textBaseline = 'middle';
                    ctx.textAlign = 'left';
                    const taskText = this.truncateText(ctx, task.name, width - 10);
                    ctx.fillText(taskText, startX + 6, y + height / 2);
                }

                ctx.globalAlpha = 1.0;

                // Resize handles
                if (isHovered) {
                    ctx.fillStyle = '#ffffff';
                    ctx.strokeStyle = '#495057';
                    ctx.lineWidth = 1;

                    // Left handle
                    ctx.beginPath();
                    ctx.arc(startX + 4, y + height / 2, 4, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();

                    // Right handle
                    ctx.beginPath();
                    ctx.arc(startX + width - 4, y + height / 2, 4, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();
                }
            }

            task._rect = { x: startX, y, width, height };
        });

        ctx.restore();
    }

    drawDependencies(ctx, data, dates, rect) {
        if (!this.props.showDependencies) {
            return;
        }
        const rows = this.getRows(data);
        // A task can appear in several groups (e.g. grouped by assignee); pin
        // dependencies to its first visible row.
        const rects = new Map();
        for (const row of rows) {
            if (row.type === 'task' && row.task._rect && !rects.has(row.task.id)) {
                rects.set(row.task.id, row.task._rect);
            }
        }
        if (!rects.size) {
            return;
        }
        ctx.save();
        ctx.beginPath();
        ctx.rect(this.sidebarWidth, 0, rect.width - this.sidebarWidth, rect.height);
        ctx.clip();
        for (const row of rows) {
            if (row.type !== 'task' || !row.task._rect) {
                continue;
            }
            for (const predecessorId of row.task.predecessor_ids || []) {
                const from = rects.get(predecessorId);
                if (from) {
                    this.drawDependencyArrow(ctx, from, row.task._rect);
                }
            }
        }
        ctx.restore();
    }

    drawDependencyArrow(ctx, from, to) {
        const startX = from.x + from.width;
        const startY = from.y + from.height / 2;
        const endX = to.x;
        const endY = to.y + to.height / 2;
        const stub = 8;
        const arrowSize = 5;

        ctx.strokeStyle = '#6c757d';
        ctx.fillStyle = '#6c757d';
        ctx.lineWidth = 1.2;

        if (Math.abs(endY - startY) < 1) {
            // Same row: straight arrow.
            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(endX, endY);
            ctx.stroke();
            this.drawArrowHead(ctx, endX, endY, endX >= startX ? 'right' : 'left', arrowSize);
            return;
        }

        if (endX >= startX + stub * 2) {
            // Normal finish-to-start: elbow into the successor's start edge.
            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(startX + stub, startY);
            ctx.lineTo(startX + stub, endY);
            ctx.lineTo(endX, endY);
            ctx.stroke();
            this.drawArrowHead(ctx, endX, endY, 'right', arrowSize);
            return;
        }

        // Successor starts at or before the predecessor's end: route through
        // the gap between the two rows, then around to the successor's left
        // side and enter its start edge from the left.
        const stubX = startX + stub;
        const below = to.y > from.y;
        const gapY = below ? to.y - 4 : to.y + to.height + 4;
        const entryX = endX - stub;
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(stubX, startY);
        ctx.lineTo(stubX, gapY);
        ctx.lineTo(entryX, gapY);
        ctx.lineTo(entryX, endY);
        ctx.lineTo(endX, endY);
        ctx.stroke();
        this.drawArrowHead(ctx, endX, endY, 'right', arrowSize);
    }

    drawArrowHead(ctx, x, y, direction, size) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        if (direction === 'right') {
            ctx.lineTo(x - size, y - size * 0.7);
            ctx.lineTo(x - size, y + size * 0.7);
        } else if (direction === 'left') {
            ctx.lineTo(x + size, y - size * 0.7);
            ctx.lineTo(x + size, y + size * 0.7);
        } else if (direction === 'down') {
            ctx.lineTo(x - size * 0.7, y - size);
            ctx.lineTo(x + size * 0.7, y - size);
        } else {
            ctx.lineTo(x - size * 0.7, y + size);
            ctx.lineTo(x + size * 0.7, y + size);
        }
        ctx.closePath();
        ctx.fill();
    }

    drawScrollbar(ctx, rect) {
        const rows = this.getRows(this.props.data);
        const viewportHeight = rect.height - this.headerHeight;
        const contentHeight = rows.length * this.cellHeight;
        if (contentHeight <= viewportHeight) {
            this.scrollbarMetrics = null;
            this.scrollbarRect = null;
            return;
        }

        const trackWidth = this.scrollbarWidth;
        const trackX = rect.width - trackWidth;
        const trackY = this.headerHeight;
        const trackHeight = viewportHeight;
        const thumbHeight = Math.max(24, (viewportHeight / contentHeight) * trackHeight);
        const maxScrollY = contentHeight - viewportHeight;
        const thumbY = trackY + (this.state.scrollY / maxScrollY) * (trackHeight - thumbHeight);

        // track
        ctx.fillStyle = 'rgba(0, 0, 0, 0.06)';
        ctx.fillRect(trackX, trackY, trackWidth, trackHeight);

        // thumb
        ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
        ctx.fillRect(trackX + 2, thumbY, trackWidth - 4, thumbHeight);

        this.scrollbarMetrics = { trackX, trackY, trackWidth, trackHeight, thumbHeight, thumbY, maxScrollY };
        this.scrollbarRect = { x: trackX, y: thumbY, width: trackWidth, height: thumbHeight };
    }

    roundRect(ctx, x, y, width, height, radius, fill, stroke) {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + width - radius, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        ctx.lineTo(x + width, y + height - radius);
        ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        ctx.lineTo(x + radius, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
        
        if (fill) ctx.fill();
        if (stroke) ctx.stroke();
    }

    truncateText(ctx, text, maxWidth) {
        const width = ctx.measureText(text).width;
        if (width <= maxWidth) return text;
        
        const ellipsis = '...';
        const ellipsisWidth = ctx.measureText(ellipsis).width;
        let truncated = text;
        
        while (ctx.measureText(truncated).width + ellipsisWidth > maxWidth && truncated.length > 0) {
            truncated = truncated.slice(0, -1);
        }
        
        return truncated + ellipsis;
    }

    // Accept either a hex string or an Odoo color index (0 = theme default).
    resolveTaskColor(task) {
        const color = task && task.color;
        if (typeof color === 'string' &&
            /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(color)) {
            return color;
        }
        const index = Number.parseInt(color, 10);
        if (Number.isInteger(index) && index > 0 && TASK_COLOR_PALETTE[index]) {
            return TASK_COLOR_PALETTE[index];
        }
        return this.colorToHex(this.getThemeColor());
    }

    hexToRgb(color) {
        let value = String(color).replace('#', '');
        if (value.length === 3) {
            value = value.split('').map((c) => c + c).join('');
        }
        return {
            r: parseInt(value.slice(0, 2), 16) || 0,
            g: parseInt(value.slice(2, 4), 16) || 0,
            b: parseInt(value.slice(4, 6), 16) || 0,
        };
    }

    // Resolve the current theme primary (the "menu color") from CSS variables so
    // bars and dots follow web_company_color instead of a hardcoded palette.
    getThemeColor() {
        if (this._themeColor) {
            return this._themeColor;
        }
        const rootStyle = getComputedStyle(document.documentElement);
        for (const raw of [
            rootStyle.getPropertyValue('--bs-primary'),
            rootStyle.getPropertyValue('--o-cc1-btn-primary'),
        ]) {
            const rgb = this.parseCssColor(raw);
            if (rgb) {
                this._themeColor = rgb;
                return rgb;
            }
        }
        this._themeColor = { r: 0x71, g: 0x4b, b: 0x67 };
        return this._themeColor;
    }

    parseCssColor(value) {
        if (typeof value !== 'string') {
            return null;
        }
        const v = value.trim();
        if (!v) {
            return null;
        }
        const hex = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.exec(v);
        if (hex) {
            let h = hex[1];
            if (h.length === 3) {
                h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
            }
            return {
                r: parseInt(h.slice(0, 2), 16),
                g: parseInt(h.slice(2, 4), 16),
                b: parseInt(h.slice(4, 6), 16),
            };
        }
        const rgb = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(v);
        if (rgb) {
            const clamp = (n) => Math.min(255, Math.max(0, Math.round(parseFloat(n))));
            return {
                r: clamp(rgb[1]),
                g: clamp(rgb[2]),
                b: clamp(rgb[3]),
            };
        }
        return null;
    }

    colorToHex(rgb) {
        const to2 = (n) => Math.round(n).toString(16).padStart(2, '0');
        return `#${to2(rgb.r)}${to2(rgb.g)}${to2(rgb.b)}`;
    }

    lighten(rgb, amount) {
        return {
            r: Math.round(rgb.r + (255 - rgb.r) * amount),
            g: Math.round(rgb.g + (255 - rgb.g) * amount),
            b: Math.round(rgb.b + (255 - rgb.b) * amount),
        };
    }

    colorLuminance(rgb) {
        const [r, g, b] = [rgb.r, rgb.g, rgb.b].map((c) => {
            const s = c / 255;
            return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    getTaskAt(x, y) {
        for (const group of this.props.data) {
            for (const task of group.tasks) {
                if (task._rect &&
                    x >= task._rect.x &&
                    x <= task._rect.x + task._rect.width &&
                    y >= task._rect.y &&
                    y <= task._rect.y + task._rect.height) {
                    return task;
                }
            }
        }
        return null;
    }

    dateToX(date, dates) {
        const scale = this.props.scale || 'day';
        // Ensure we're working with local dates to avoid timezone issues
        const localDate = new Date(date.getTime() - (date.getTimezoneOffset() * 60000));
        const localStart = new Date(dates.start.getTime() - (dates.start.getTimezoneOffset() * 60000));
        
        const days = (localDate - localStart) / 86400000;
        if (scale === 'day') {
            return this.sidebarWidth + days * this.cellWidth - this.state.scrollX;
        } else if (scale === 'week') {
            const weeks = days / 7.0;
            return this.sidebarWidth + weeks * this.cellWidth - this.state.scrollX;
        } else if (scale === 'quarter') {
            const months = (localDate.getFullYear() - localStart.getFullYear()) * 12 + (localDate.getMonth() - localStart.getMonth()) + (localDate.getDate()-1)/30;
            return this.sidebarWidth + (months / 3) * this.cellWidth - this.state.scrollX;
        } else {
            // month: one column per month
            const months = (localDate.getFullYear() - localStart.getFullYear()) * 12 + (localDate.getMonth() - localStart.getMonth()) + (localDate.getDate()-1)/30;
            return this.sidebarWidth + months * this.cellWidth - this.state.scrollX;
        }
    }

    xToDate(x, dates) {
        const scale = this.props.scale || 'day';
        // Ensure we're working with local dates to avoid timezone issues
        const localStart = new Date(dates.start.getTime() - (dates.start.getTimezoneOffset() * 60000));
        
        if (scale === 'day') {
            const days = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const result = new Date(localStart.getTime() + days * 86400000);
            // Convert back to local timezone
            return new Date(result.getTime() + (result.getTimezoneOffset() * 60000));
        } else if (scale === 'week') {
            const weeks = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const days = weeks * 7.0;
            const result = new Date(localStart.getTime() + days * 86400000);
            return new Date(result.getTime() + (result.getTimezoneOffset() * 60000));
        } else if (scale === 'quarter') {
            const quarters = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const start = new Date(localStart.getFullYear(), localStart.getMonth(), 1);
            start.setMonth(start.getMonth() + Math.round(quarters * 3));
            return new Date(start.getTime() + (start.getTimezoneOffset() * 60000));
        } else {
            // month scale
            const months = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const start = new Date(localStart.getFullYear(), localStart.getMonth(), 1);
            start.setMonth(start.getMonth() + months);
            return new Date(start.getTime() + (start.getTimezoneOffset() * 60000));
        }
    }

    dispatchEvent(name, detail) {
        this.root.el.dispatchEvent(new CustomEvent(name, { bubbles: true, detail }));
    }

    onMouseDown(e) {
        const rect = this.canvasRef.el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // Vertical scrollbar drag (works in view and edit mode)
        if (this.scrollbarRect && x >= this.scrollbarRect.x) {
            this.state.scrollbarDragging = true;
            this._scrollbarDragOffset = y - this.scrollbarRect.y;
            this.canvasRef.el.style.cursor = 'grabbing';
            return;
        }

        // Grab the divider between the sidebar and the timeline to resize the
        // sidebar. Checked before the sidebar click handling below so the
        // handle works from both sides of the boundary.
        if (Math.abs(x - this.sidebarWidth) <= 6) {
            this._sidebarResize = {
                startClientX: e.clientX,
                startWidth: this.sidebarWidth,
            };
            this.canvasRef.el.style.cursor = 'col-resize';
            return;
        }

        // The left sidebar opens the task form on click (see onClick); it is
        // not a drag/pan surface.
        if (x < this.sidebarWidth) {
            return;
        }

        if (!this.props.editable) {
            return;
        }
        const task = this.getTaskAt(x, y);

        if (task) {
            this.state.draggedTask = {
                ...task,
                startX: e.clientX,
                originalStart: new Date(task.start_date),
                originalEnd: this.getTaskEndDate(task),
            };
            this.state.tooltip.visible = false;
            this.canvasRef.el.style.cursor = 'grabbing';
        } else {
            // begin panning when clicking empty area
            this.state.isPanning = true;
            this.state.panStartX = e.clientX;
            this.canvasRef.el.style.cursor = 'grabbing';
        }
    }

    onMouseMove(e) {
        const rect = this.canvasRef.el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        if (this.state.scrollbarDragging && this.scrollbarMetrics) {
            const m = this.scrollbarMetrics;
            const thumbY = y - this._scrollbarDragOffset;
            const ratio = (thumbY - m.trackY) / (m.trackHeight - m.thumbHeight);
            this.state.scrollY = ratio * m.maxScrollY;
            this.clampScrollIntoView();
            this.scheduleRedraw();
            return;
        }

        if (this._sidebarResize) {
            const delta = e.clientX - this._sidebarResize.startClientX;
            const maxWidth = Math.max(
                this.minSidebarWidth,
                Math.min(this.maxSidebarWidth, rect.width * 0.7)
            );
            this.sidebarWidth = Math.round(
                Math.max(
                    this.minSidebarWidth,
                    Math.min(maxWidth, this._sidebarResize.startWidth + delta)
                )
            );
            this.clampScrollIntoView();
            this.scheduleRedraw();
            return;
        }

        // The resize handle covers both sides of the divider.
        if (Math.abs(x - this.sidebarWidth) <= 6) {
            this.canvasRef.el.style.cursor = 'col-resize';
            this.state.tooltip.visible = false;
            if (this.state.hoveredTask) {
                this.state.hoveredTask = null;
                this.scheduleRedraw();
            }
            return;
        }

        if (x < this.sidebarWidth) {
            const row = this.getRowAtY(y);
            const caret = row && row._caretRect;
            const overCaret = !!caret && x >= caret.x && x <= caret.x + caret.width;
            this.canvasRef.el.style.cursor = overCaret ? 'pointer' : 'default';
            // Sidebar labels are truncated to fit; show the full text of the
            // hovered row in a tooltip.
            if (row && y >= this.headerHeight) {
                this.state.tooltip = {
                    visible: true,
                    content:
                        row.type === 'group'
                            ? `${row.group.name} (${row.group.tasks.length})`
                            : row.task.name,
                    x,
                    y,
                };
            } else {
                this.state.tooltip.visible = false;
            }
            if (this.state.hoveredTask) {
                this.state.hoveredTask = null;
                this.scheduleRedraw();
            }
            return;
        }

        if (this.state.draggedTask) {
            const { originalStart, originalEnd, startX } = this.state.draggedTask;
            const deltaX = e.clientX - startX;
            const scale = this.props.scale || 'day';

            let newStartDate, newEndDate;
            if (scale === 'month') {
                // One cell is one month at month scale, so snap to whole months.
                const monthsDelta = Math.round(deltaX / this.cellWidth);
                newStartDate = this.addMonths(originalStart, monthsDelta);
                newEndDate = this.addMonths(originalEnd, monthsDelta);
            } else if (scale === 'quarter') {
                // One cell is one quarter at quarter scale.
                const quartersDelta = Math.round(deltaX / this.cellWidth);
                newStartDate = this.addMonths(originalStart, quartersDelta * 3);
                newEndDate = this.addMonths(originalEnd, quartersDelta * 3);
            } else {
                // One cell is a week at week scale and a day otherwise.
                const daysPerCell = scale === 'week' ? 7 : 1;
                const daysDelta = Math.round((deltaX / this.cellWidth) * daysPerCell);
                const msDelta = daysDelta * 86400000;
                newStartDate = new Date(originalStart.getTime() + msDelta);
                newEndDate = new Date(originalEnd.getTime() + msDelta);
            }

            const taskInUI = this.props.data
                .flatMap(g => g.tasks)
                .find(t => t.id === this.state.draggedTask.id);
            
            if (taskInUI) {
                // Format dates consistently in local time for Odoo
                taskInUI.start_date = this.formatDateLocal(newStartDate);
                taskInUI.end_date = this.formatDateLocal(newEndDate);
                this.scheduleRedraw();
            }
        } else if (this.state.isPanning) {
            const dx = e.clientX - this.state.panStartX;
            this.state.panStartX = e.clientX;
            this.state.scrollX -= dx;
            this.clampScrollIntoView();
            this.scheduleRedraw();
        } else {
            const task = this.getTaskAt(x, y);
            this.state.hoveredTask = task;
            const marker = task ? null : this.getMarkerAt(x, y);

            if (task) {
                const start = new Date(task.start_date);
                const end = this.getTaskEndDate(task);
                const startDate = start.toLocaleDateString();
                const endDate = end.toLocaleDateString();
                const duration = ((end - start) / 86400000).toFixed(1);

                this.state.tooltip = {
                    visible: true,
                    content: `${task.name}\nStart: ${startDate}\nEnd: ${endDate}\nDuration: ${duration} days\nProgress: ${task.progress}%`,
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top,
                };
                this.canvasRef.el.style.cursor = 'grab';
            } else if (marker) {
                this.state.tooltip = {
                    visible: true,
                    content: this.formatMarkerTooltip(marker),
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top,
                };
                this.canvasRef.el.style.cursor = 'default';
            } else {
                this.state.tooltip.visible = false;
                this.canvasRef.el.style.cursor = 'default';
            }
            
            this.scheduleRedraw();
        }
    }

    onMouseUp(e) {
        if (this._sidebarResize) {
            this._sidebarResize = null;
            // The browser fires a click after mouseup; swallow it so the row
            // under the divider does not also open the task form.
            this._suppressClick = true;
            this.canvasRef.el.style.cursor = 'default';
            this.scheduleRedraw();
            return;
        }
        if (this.state.scrollbarDragging) {
            this.state.scrollbarDragging = false;
            this.canvasRef.el.style.cursor = 'default';
            return;
        }
        if (this.state.draggedTask) {
            const task = this.props.data
                .flatMap(g => g.tasks)
                .find(t => t.id === this.state.draggedTask.id);
            
            if (task) {
                this.dispatchEvent('task-updated', {
                    taskId: task.id,
                    startDate: task.start_date,
                    endDate: task.end_date,
                });
            }
            
            this.state.draggedTask = null;
            this.canvasRef.el.style.cursor = 'default';
        } else if (this.state.isPanning) {
            this.state.isPanning = false;
            this.canvasRef.el.style.cursor = 'default';
        }
    }

    onClick(e) {
        if (this._suppressClick) {
            this._suppressClick = false;
            return;
        }
        const rect = this.canvasRef.el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        // Only the left sidebar opens the task form; clicking a task bar in
        // the chart area does nothing (it is a drag surface).
        if (x >= this.sidebarWidth) {
            return;
        }
        const row = this.getRowAtY(y);
        if (!row || row.type !== 'task') {
            return;
        }
        const caret = row._caretRect;
        if (row.hasChildren && caret && x >= caret.x && x <= caret.x + caret.width) {
            this.toggleCollapse(row.task.id);
            return;
        }
        this.dispatchEvent('task-clicked', { taskId: row.task.id });
    }

    toggleCollapse(taskId) {
        if (this.state.collapsedIds[taskId]) {
            delete this.state.collapsedIds[taskId];
        } else {
            this.state.collapsedIds[taskId] = true;
        }
        this.clampScrollIntoView();
        this.drawGantt();
    }

    getWeekNumber(date) {
        const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
        const dayNum = d.getUTCDay() || 7;
        d.setUTCDate(d.getUTCDate() + 4 - dayNum);
        const yearStart = new Date(Date.UTC(d.getUTCFullYear(),0,1));
        return Math.ceil((((d - yearStart) / 86400000) + 1)/7);
    }

    onWheel(e) {
        e.preventDefault();
        
        if (e.ctrlKey || e.metaKey) {
            // Ctrl/Cmd + wheel for zoom
            const zoomDelta = e.deltaY > 0 ? 0.9 : 1.1;
            const oldZoom = this.state.zoom;
            this.state.zoom = Math.max(0.5, Math.min(2.0, this.state.zoom * zoomDelta));
            // Keep content centered
            const zoomRatio = this.state.zoom / oldZoom;
            this.state.scrollX = this.state.scrollX * zoomRatio;
            this.state.scrollY = this.state.scrollY * zoomRatio;
            this.clampScrollIntoView();
        } else if (e.shiftKey) {
            // Shift + wheel pans vertically
            this.state.scrollY = this.state.scrollY + e.deltaY;
            this.clampScrollIntoView();
        } else {
            // Left sidebar: vertical scroll. Gantt bar area: horizontal scroll.
            const rect = this.canvasRef.el.getBoundingClientRect();
            const x = e.clientX - rect.left;
            if (x < this.sidebarWidth) {
                this.state.scrollY = this.state.scrollY + (e.deltaY || e.deltaX);
            } else {
                const panDelta = (e.deltaX !== 0 ? e.deltaX : e.deltaY);
                this.state.scrollX = this.state.scrollX + panDelta;
            }
            this.clampScrollIntoView();
        }
        
        this.scheduleRedraw();
    }

    handleVerticalTimeScaleNavigation(deltaY) {
        // Ordered from smallest to largest cell unit.
        const scales = ['day', 'week', 'month', 'quarter'];
        const currentScale = this.props.scale || 'day';
        const currentIndex = scales.indexOf(currentScale);
        
        if (deltaY > 0 && currentIndex > 0) {
            // Scroll up - go to smaller time scale
            this.dispatchEvent('scale-change', { scale: scales[currentIndex - 1] });
        } else if (deltaY < 0 && currentIndex < scales.length - 1) {
            // Scroll down - go to larger time scale
            this.dispatchEvent('scale-change', { scale: scales[currentIndex + 1] });
        }
    }

    handleKey(e) {
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const panStepX = Math.max(40, (rect.width - this.sidebarWidth) * 0.1);
        const panStepY = this.cellHeight * 2;
        if (e.key === 'ArrowRight') {
            this.state.scrollX += panStepX;
        } else if (e.key === 'ArrowLeft') {
            this.state.scrollX -= panStepX;
        } else if (e.key === 'ArrowDown') {
            this.state.scrollY += panStepY;
        } else if (e.key === 'ArrowUp') {
            this.state.scrollY -= panStepY;
        } else if (e.key === 'Home') {
            this.handleNavigate({ type: 'today' });
            return;
        } else if ((e.key === '+' || e.key === '=') && (e.ctrlKey || e.metaKey)) {
            // Ctrl + '+' zoom in
            this.onWheel({ preventDefault: () => {}, ctrlKey: true, metaKey: false, deltaY: -1 });
            return;
        } else if ((e.key === '-' || e.key === '_') && (e.ctrlKey || e.metaKey)) {
            // Ctrl + '-' zoom out
            this.onWheel({ preventDefault: () => {}, ctrlKey: true, metaKey: false, deltaY: 1 });
            return;
        } else if (e.altKey && (e.key === 'PageUp' || e.key === 'PageDown')) {
            // Alt + PageUp/PageDown to change time scale
            const delta = e.key === 'PageUp' ? -1 : 1;
            this.handleVerticalTimeScaleNavigation(delta);
        } else {
            return;
        }
        this.clampScrollIntoView();
        this.scheduleRedraw();
    }

    handleNavigate(detail) {
        if (!detail) return;
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const data = this.props.data;
        const dates = this.calculateDateRange(data);
        const scale = this.props.scale || 'day';

        if (detail.type === 'today') {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const xToday = this.dateToX(today, dates);
            // Center today in viewport
            const centerX = this.sidebarWidth + (rect.width - this.sidebarWidth) / 2;
            this.state.scrollX = Math.max(0, xToday - centerX);
        } else if (detail.type === 'prev' || detail.type === 'next') {
            const direction = detail.type === 'prev' ? -1 : 1;
            let deltaPx = 0;
            if (scale === 'day') {
                deltaPx = this.cellWidth * 7 * direction; // about one week
            } else if (scale === 'week') {
                deltaPx = this.cellWidth * 1 * direction; // one week
            } else if (scale === 'month') {
                deltaPx = this.cellWidth * 1 * direction; // one month
            } else if (scale === 'quarter') {
                deltaPx = this.cellWidth * 1 * direction; // one quarter
            }
            // Fallback: pan by half the viewport
            if (!deltaPx) {
                deltaPx = ((rect.width - this.sidebarWidth) / 2) * direction;
            }
            this.state.scrollX = this.state.scrollX + deltaPx;
        }
        this.clampScrollIntoView();
        this.scheduleRedraw();
    }

    onMouseLeave() {
        this._sidebarResize = null;
        this.state.draggedTask = null;
        this.state.isPanning = false;
        this.state.scrollbarDragging = false;
        this.state.tooltip.visible = false;
        this.state.hoveredTask = null;
        this.canvasRef.el.style.cursor = 'default';
        this.scheduleRedraw();
    }
}