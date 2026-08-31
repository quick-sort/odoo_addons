/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState, onWillUpdateProps } from "@odoo/owl";

export class GanttRenderer extends Component {
    static template = "project_task_gantt.GanttRenderer";
    static props = {
        data: { type: Array },
        scale: { type: String },
        editable: { type: Boolean, optional: true },
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
        });

        // Base dimensions
        this.baseCellWidth = 40;
        this.baseCellHeight = 40;
        this.headerHeight = 80;
        this.sidebarWidth = 250;
        this.minCellWidth = 20;
        this.maxCellWidth = 100;

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
        });

        onWillUpdateProps(() => {
            this.scheduleRedraw();
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


    get cellWidth() {
        // Adjust base width per scale for better zooming behavior
        const scale = this.props.scale || 'month';
        const scaleFactor = (
            scale === 'day' ? 2.0 :
            scale === 'week' ? 1.2 :
            scale === 'month' ? 1.0 :
            0.6 // year
        );
        const width = this.baseCellWidth * scaleFactor * this.state.zoom;
        return Math.max(this.minCellWidth, Math.min(this.maxCellWidth, width));
    }

    get cellHeight() {
        return this.baseCellHeight;
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

        if (!data || data.length === 0) {
            this.drawEmptyState(ctx, rect);
            return;
        }

        const dates = this.calculateDateRange(data);
        if (!dates.start || !dates.end) {
            this.drawEmptyState(ctx, rect);
            return;
        }

        // Draw in layers for better visual hierarchy
        this.drawGrid(ctx, dates, data, rect);
        this.drawTodayMarker(ctx, dates, rect);
        this.drawTasks(ctx, data, dates, rect);
        this.drawHeader(ctx, dates, rect);
        this.drawSidebar(ctx, data, rect);
    }

    getMaxScrollX(rect, dates) {
        // total content width minus viewport
        const scale = this.props.scale || 'month';
        let totalUnits = 0;
        if (scale === 'week') {
            const days = Math.ceil((dates.end - dates.start) / 86400000);
            totalUnits = Math.ceil(days / 7);
        } else if (scale === 'month') {
            // Month view renders per day, so use number of days
            const days = Math.ceil((dates.end - dates.start) / 86400000);
            totalUnits = days;
        } else {
            const months = (dates.end.getFullYear() - dates.start.getFullYear()) * 12 + (dates.end.getMonth() - dates.start.getMonth()) + 1;
            totalUnits = months;
        }
        const contentWidth = this.sidebarWidth + totalUnits * this.cellWidth;
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
        this.state.scrollX = Math.max(0, Math.min(this.state.scrollX, maxX));
        this.state.scrollY = Math.max(0, this.state.scrollY);
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
            const end = new Date(t.end_date);
            if (!minDate || start < minDate) minDate = start;
            if (!maxDate || end > maxDate) maxDate = end;
        }));

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

    drawGrid(ctx, dates, data, rect) {
        ctx.strokeStyle = '#e9e9e9';
        ctx.lineWidth = 1;

        const days = Math.ceil((dates.end - dates.start) / 86400000);

        // Vertical grid lines (dates) with scale support
        const scale = this.props.scale || 'month';
        if (scale === 'day' || scale === 'month') {
            for (let i = 0; i <= days; i++) {
                const x = this.sidebarWidth + i * this.cellWidth - this.state.scrollX;
                if (x >= this.sidebarWidth && x <= rect.width) {
                    ctx.beginPath();
                    ctx.moveTo(x, this.headerHeight);
                    ctx.lineTo(x, rect.height);
                    ctx.stroke();
                }
            }
        } else if (scale === 'week') {
            let current = new Date(dates.start);
            current.setDate(current.getDate() - current.getDay());
            while (current <= dates.end) {
                const x = this.dateToX(current, dates);
                if (x >= this.sidebarWidth && x <= rect.width) {
                    ctx.beginPath();
                    ctx.moveTo(x, this.headerHeight);
                    ctx.lineTo(x, rect.height);
                    ctx.stroke();
                }
                current.setDate(current.getDate() + 7);
            }
        } else if (scale === 'year') {
            let current = new Date(dates.start.getFullYear(), dates.start.getMonth(), 1);
            while (current <= dates.end) {
                const x = this.dateToX(current, dates);
                if (x >= this.sidebarWidth && x <= rect.width) {
                    ctx.beginPath();
                    ctx.moveTo(x, this.headerHeight);
                    ctx.lineTo(x, rect.height);
                    ctx.stroke();
                }
                current.setMonth(current.getMonth() + 1);
            }
        }

        // Horizontal grid lines (tasks)
        let totalRows = data.reduce((acc, g) => acc + Math.max(g.tasks.length, 1), 0);
        for (let i = 0; i <= totalRows; i++) {
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

        // Draw header according to scale
        ctx.fillStyle = '#495057';
        ctx.font = 'bold 13px Arial';
        ctx.textBaseline = 'top';
        const scale = this.props.scale || 'month';
        if (scale === 'day') {
            let current = new Date(dates.start);
            while (current <= dates.end) {
                const monthX = this.dateToX(new Date(current.getFullYear(), current.getMonth(), 1), dates);
                const monthName = current.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
                ctx.fillText(monthName, Math.max(this.sidebarWidth + 5, monthX + 5), 15);
                current.setMonth(current.getMonth() + 1);
            }
            ctx.font = '11px Arial';
            ctx.fillStyle = '#6c757d';
            let dayCounter = new Date(dates.start);
            const days = Math.ceil((dates.end - dates.start) / 86400000);
            for (let i = 0; i <= days; i++) {
                const dayX = this.dateToX(dayCounter, dates);
                const day = dayCounter.getDate();
                const dayOfWeek = dayCounter.toLocaleDateString('en-US', { weekday: 'short' });
                ctx.fillText(day.toString(), dayX + 5, 45);
                ctx.fillText(dayOfWeek, dayX + 5, 60);
                dayCounter.setDate(dayCounter.getDate() + 1);
            }
        } else if (scale === 'week') {
            let current = new Date(dates.start);
            while (current <= dates.end) {
                const monthX = this.dateToX(new Date(current.getFullYear(), current.getMonth(), 1), dates);
                const monthName = current.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
                if (monthX >= this.sidebarWidth && monthX <= rect.width) {
                    ctx.fillText(monthName, Math.max(this.sidebarWidth + 5, monthX + 5), 15);
                }
                current.setMonth(current.getMonth() + 1);
            }
            ctx.font = '11px Arial';
            ctx.fillStyle = '#6c757d';
            let weekStart = new Date(dates.start);
            weekStart.setDate(weekStart.getDate() - weekStart.getDay());
            while (weekStart <= dates.end) {
                const weekX = this.dateToX(weekStart, dates);
                const weekLabel = `W${this.getWeekNumber(weekStart)}`;
                ctx.fillText(weekLabel, weekX + 5, 50);
                weekStart.setDate(weekStart.getDate() + 7);
            }
        } else if (scale === 'month') {
            let current = new Date(dates.start);
            while (current <= dates.end) {
                const monthX = this.dateToX(new Date(current.getFullYear(), current.getMonth(), 1), dates);
                const monthName = current.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
                if (monthX >= this.sidebarWidth && monthX <= rect.width) {
                    ctx.fillText(monthName, Math.max(this.sidebarWidth + 5, monthX + 5), 15);
                }
                current.setMonth(current.getMonth() + 1);
            }
            ctx.font = '11px Arial';
            ctx.fillStyle = '#6c757d';
            let dayCounter = new Date(dates.start);
            const days = Math.ceil((dates.end - dates.start) / 86400000);
            for (let i = 0; i <= days; i++) {
                const dayX = this.dateToX(dayCounter, dates);
                const isWeekend = dayCounter.getDay() === 0 || dayCounter.getDay() === 6;
                if (isWeekend) {
                    ctx.fillStyle = '#e9ecef';
                    ctx.fillRect(dayX, this.headerHeight, this.cellWidth, rect.height - this.headerHeight);
                    ctx.fillStyle = '#6c757d';
                }
                const day = dayCounter.getDate();
                ctx.fillText(day.toString(), dayX + 5, 50);
                dayCounter.setDate(dayCounter.getDate() + 1);
            }
        } else if (scale === 'year') {
            let currentYear = dates.start.getFullYear();
            while (currentYear <= dates.end.getFullYear()) {
                const yearX = this.dateToX(new Date(currentYear, 0, 1), dates);
                if (yearX >= this.sidebarWidth && yearX <= rect.width) {
                    ctx.fillText(String(currentYear), Math.max(this.sidebarWidth + 5, yearX + 5), 15);
                }
                currentYear++;
            }
            ctx.font = '11px Arial';
            ctx.fillStyle = '#6c757d';
            let current = new Date(dates.start.getFullYear(), dates.start.getMonth(), 1);
            while (current <= dates.end) {
                const monthX = this.dateToX(current, dates);
                const monthName = current.toLocaleDateString('en-US', { month: 'short' });
                ctx.fillText(monthName, monthX + 5, 50);
                current.setMonth(current.getMonth() + 1);
            }
        }

        ctx.restore();
    }

    drawSidebar(ctx, data, rect) {
        // Background
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, this.headerHeight, this.sidebarWidth, rect.height);
        
        ctx.strokeStyle = '#dee2e6';
        ctx.strokeRect(0, 0, this.sidebarWidth, rect.height);

        ctx.save();
        ctx.beginPath();
        ctx.rect(0, this.headerHeight, this.sidebarWidth, rect.height - this.headerHeight);
        ctx.clip();

        ctx.fillStyle = '#495057';
        ctx.font = 'bold 12px Arial';
        ctx.textBaseline = 'middle';
        
        let y = this.headerHeight - this.state.scrollY;
        
        data.forEach(group => {
            const taskCount = Math.max(group.tasks.length, 1);
            const groupHeight = taskCount * this.cellHeight;
            const textY = y + groupHeight / 2;
            
            if (y + groupHeight > this.headerHeight && y < rect.height) {
                // Group background alternating color
                ctx.fillStyle = 'rgba(0, 0, 0, 0.02)';
                ctx.fillRect(0, Math.max(y, this.headerHeight), this.sidebarWidth, Math.min(groupHeight, rect.height - y));
                
                // Group name
                ctx.fillStyle = '#495057';
                const groupText = `${group.name} (${group.tasks.length})`;
                const truncated = this.truncateText(ctx, groupText, this.sidebarWidth - 20);
                ctx.fillText(truncated, 10, textY);
                
                // Separator line
                ctx.strokeStyle = '#dee2e6';
                ctx.beginPath();
                ctx.moveTo(0, y + groupHeight);
                ctx.lineTo(this.sidebarWidth, y + groupHeight);
                ctx.stroke();
            }
            
            y += groupHeight;
        });

        ctx.restore();
    }

    drawTasks(ctx, data, dates, rect) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(this.sidebarWidth, this.headerHeight, rect.width - this.sidebarWidth, rect.height - this.headerHeight);
        ctx.clip();

        let taskRow = 0;
        
        data.forEach(group => {
            if (group.tasks.length === 0) {
                taskRow++;
                return;
            }
            
            group.tasks.forEach(task => {
                const start = new Date(task.start_date);
                const end = new Date(task.end_date);
                
                // If end time is exactly midnight (00:00:00), treat it as end of previous day
                if (end.getHours() === 0 && end.getMinutes() === 0 && end.getSeconds() === 0) {
                    end.setDate(end.getDate() - 1);
                    end.setHours(23, 59, 59, 999);
                }
                
                const startX = this.dateToX(start, dates);
                const endX = this.dateToX(end, dates);
                const width = Math.max(endX - startX, 5);
                const y = this.headerHeight + (taskRow * this.cellHeight) + 6 - this.state.scrollY;
                const height = this.cellHeight - 12;

                if (y + this.cellHeight > this.headerHeight && y < rect.height) {
                    const isHovered = this.state.hoveredTask?.id === task.id;
                    const isDragged = this.state.draggedTask?.id === task.id;
                    
                    // Task bar shadow
                    if (isHovered || isDragged) {
                        ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
                        ctx.shadowBlur = 10;
                        ctx.shadowOffsetY = 3;
                    }
                    
                    // Task bar background
                    ctx.fillStyle = this.getTaskColor(task);
                    if (isDragged) {
                        ctx.globalAlpha = 0.7;
                    }
                    
                    this.roundRect(ctx, startX, y, width, height, 6, true, false);
                    
                    ctx.shadowColor = 'transparent';
                    ctx.shadowBlur = 0;
                    ctx.shadowOffsetY = 0;
                    
                    // Progress bar
                    if (task.progress > 0) {
                        ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
                        const progressWidth = (width - 4) * (task.progress / 100);
                        this.roundRect(ctx, startX + 2, y + 2, progressWidth, height - 4, 4, true, false);
                    }
                    
                    // Task name
                    if (width > 40) {
                        ctx.fillStyle = '#ffffff';
                        ctx.font = isHovered ? 'bold 11px Arial' : '11px Arial';
                        ctx.textBaseline = 'middle';
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
                taskRow++;
            });
        });

        ctx.restore();
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

    getTaskColor(task) {
        const colors = [
            '#875a7b', '#f06050', '#f4a460', '#6cc1ed', 
            '#d6145f', '#30c381', '#9c27b0', '#ff9800'
        ];
        return colors[task.color % colors.length] || '#875a7b';
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
        const scale = this.props.scale || 'month';
        // Ensure we're working with local dates to avoid timezone issues
        const localDate = new Date(date.getTime() - (date.getTimezoneOffset() * 60000));
        const localStart = new Date(dates.start.getTime() - (dates.start.getTimezoneOffset() * 60000));
        
        const days = (localDate - localStart) / 86400000;
        if (scale === 'day' || scale === 'month') {
            return this.sidebarWidth + days * this.cellWidth - this.state.scrollX;
        } else if (scale === 'week') {
            const weeks = days / 7.0;
            return this.sidebarWidth + weeks * this.cellWidth - this.state.scrollX;
        } else {
            // year: months resolution
            const months = (localDate.getFullYear() - localStart.getFullYear()) * 12 + (localDate.getMonth() - localStart.getMonth()) + (localDate.getDate()-1)/30;
            return this.sidebarWidth + months * this.cellWidth - this.state.scrollX;
        }
    }

    xToDate(x, dates) {
        const scale = this.props.scale || 'month';
        // Ensure we're working with local dates to avoid timezone issues
        const localStart = new Date(dates.start.getTime() - (dates.start.getTimezoneOffset() * 60000));
        
        if (scale === 'day' || scale === 'month') {
            const days = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const result = new Date(localStart.getTime() + days * 86400000);
            // Convert back to local timezone
            return new Date(result.getTime() + (result.getTimezoneOffset() * 60000));
        } else if (scale === 'week') {
            const weeks = (x - this.sidebarWidth + this.state.scrollX) / this.cellWidth;
            const days = weeks * 7.0;
            const result = new Date(localStart.getTime() + days * 86400000);
            return new Date(result.getTime() + (result.getTimezoneOffset() * 60000));
        } else {
            // year scale
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
        if (!this.props.editable) {
            return;
        }
        const rect = this.canvasRef.el.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const task = this.getTaskAt(x, y);
        
        if (task) {
            this.state.draggedTask = {
                ...task,
                startX: e.clientX,
                originalStart: new Date(task.start_date),
                originalEnd: new Date(task.end_date),
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

        if (this.state.draggedTask) {
            const deltaX = e.clientX - this.state.draggedTask.startX;
            const daysDelta = Math.round(deltaX / this.cellWidth);
            const msDelta = daysDelta * 86400000;
            
            const newStartDate = new Date(this.state.draggedTask.originalStart.getTime() + msDelta);
            const newEndDate = new Date(this.state.draggedTask.originalEnd.getTime() + msDelta);
            
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
            
            if (task) {
                const startDate = new Date(task.start_date).toLocaleDateString();
                const endDate = new Date(task.end_date).toLocaleDateString();
                const duration = ((new Date(task.end_date) - new Date(task.start_date)) / 86400000).toFixed(1);
                
                this.state.tooltip = {
                    visible: true,
                    content: `${task.name}\nStart: ${startDate}\nEnd: ${endDate}\nDuration: ${duration} days\nProgress: ${task.progress}%`,
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top,
                };
                this.canvasRef.el.style.cursor = 'grab';
            } else {
                this.state.tooltip.visible = false;
                this.canvasRef.el.style.cursor = 'default';
            }
            
            this.scheduleRedraw();
        }
    }

    onMouseUp(e) {
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

    onDoubleClick(e) {
        const rect = this.canvasRef.el.getBoundingClientRect();
        const task = this.getTaskAt(e.clientX - rect.left, e.clientY - rect.top);
        
        if (task) {
            this.dispatchEvent('task-clicked', { taskId: task.id });
        }
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
            // Default wheel pans horizontally; vertical wheel mapped to horizontal pan
        // Nudge horizontally; when headers are stacked off-screen, just pan without showing negative space
        const panDelta = (e.deltaX !== 0 ? e.deltaX : e.deltaY);
        this.state.scrollX = this.state.scrollX + panDelta;
            this.clampScrollIntoView();
        }
        
        this.scheduleRedraw();
    }

    handleVerticalTimeScaleNavigation(deltaY) {
        // Day scale removed per requirements
        const scales = ['week', 'month', 'year'];
        const currentScale = this.props.scale || 'month';
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
        const scale = this.props.scale || 'month';

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
            if (scale === 'week') {
                deltaPx = this.cellWidth * 1 * direction; // one week
            } else if (scale === 'month') {
                deltaPx = this.cellWidth * 7 * direction; // approx one week jump
            } else if (scale === 'year') {
                deltaPx = this.cellWidth * 1 * direction; // one month at year scale
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
        this.state.draggedTask = null;
        this.state.isPanning = false;
        this.state.tooltip.visible = false;
        this.state.hoveredTask = null;
        this.canvasRef.el.style.cursor = 'default';
        this.scheduleRedraw();
    }
}