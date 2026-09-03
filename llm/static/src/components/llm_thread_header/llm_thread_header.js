/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { LLMRelatedRecord } from "../llm_related_record/llm_related_record";
import { useService } from "@web/core/utils/hooks";

/**
 * Thread Header Component
 * Displays thread name and provides a dropdown for assistant selection
 */
export class LLMThreadHeader extends Component {
  static template = "llm.LLMThreadHeader";
  static components = { Dropdown, DropdownItem, LLMRelatedRecord };

  setup() {
    this.llmStore = useState(useService("llm.store"));
    this.mailStore = useState(useService("mail.store"));
    this.orm = useService("orm");
    this.notification = useService("notification");

    // Local state
    this.state = useState({
      isEditingName: false,
      pendingName: "",
      isLoadingUpdate: false,
    });

    // Refs
    this.nameInputRef = useRef("nameInput");
  }

  /**
   * Get the active thread
   */
  get activeThread() {
    return this.mailStore.discuss?.thread;
  }

  /**
   * Refresh thread fields - fetchData with fallback for compatibility
   */
  async _refreshThread(fields) {
    const thread = this.activeThread;
    if (!thread) return;
    if (typeof thread.fetchData === "function") {
      await thread.fetchData(fields);
    } else {
      const data = await this.orm.read("llm.thread", [thread.id], fields);
      if (data && data.length) {
        const raw = data[0];
        for (const f of ["assistant_id", "provider_id", "model_id"]) {
          if (Array.isArray(raw[f])) {
            raw[f] = { id: raw[f][0], name: raw[f][1] };
          }
        }
        Object.assign(thread, raw);
      }
    }
  }

  /**
   * Check if we have an active LLM thread
   */
  get hasActiveThread() {
    return this.activeThread?.model === "llm.thread";
  }

  /**
   * Get current assistant
   */
  get currentAssistant() {
    if (!this.hasActiveThread) return null;

    const assistantId =
      this.activeThread.assistant_id?.id || this.activeThread.assistant_id;
    if (!assistantId) return null;

    return this.llmStore.llmAssistants?.get(assistantId) || this.activeThread.assistant_id;
  }

  /**
   * Get available assistants
   */
  get availableAssistants() {
    return this.llmStore.llmAssistants
      ? Array.from(this.llmStore.llmAssistants.values())
      : [];
  }

  // Thread Name Management

  /**
   * Start editing thread name
   */
  startEditingName() {
    this.state.isEditingName = true;
    this.state.pendingName = this.activeThread.name || "";

    // Focus input after render
    setTimeout(() => {
      if (this.nameInputRef.el) {
        this.nameInputRef.el.focus();
        this.nameInputRef.el.select();
      }
    }, 0);
  }

  /**
   * Save thread name
   */
  async saveThreadName() {
    if (!this.state.pendingName.trim()) {
      this.notification.add(_t("Please enter a name for this conversation."), {
        type: "warning",
      });
      return;
    }

    try {
      this.state.isLoadingUpdate = true;

      // Update thread name via ORM
      await this.orm.write("llm.thread", [this.activeThread.id], {
        name: this.state.pendingName.trim(),
      });

      // Reload thread data using proper fetchData pattern
      await this._refreshThread(["name"]);

      this.state.isEditingName = false;
      this.state.pendingName = "";
    } catch (error) {
      this.notification.add(
        _t("Could not save the conversation name. Please try again."),
        {
          type: "danger",
        }
      );
      console.error("Error updating thread name:", error);
    } finally {
      this.state.isLoadingUpdate = false;
    }
  }

  /**
   * Cancel editing thread name
   */
  cancelEditingName() {
    this.state.isEditingName = false;
    this.state.pendingName = "";
  }

  /**
   * Handle keydown in name input
   * @param {KeyboardEvent} ev - Keyboard event
   */
  onNameInputKeydown(ev) {
    if (ev.key === "Enter") {
      ev.preventDefault();
      this.saveThreadName();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      this.cancelEditingName();
    }
  }

  // Assistant Management

  /**
   * Select an assistant
   * @param {Object} assistant - Assistant object to select
   */
  async selectAssistant(assistant) {
    const assistantId = assistant ? assistant.id : null;
    if (assistantId === this.currentAssistant?.id) return;

    try {
      this.state.isLoadingUpdate = true;
      await this.llmStore.selectAssistant(assistantId);
    } catch (error) {
      this.notification.add(
        _t("Could not change the assistant. Please try again."),
        {
          type: "danger",
        }
      );
      console.error("Error updating assistant:", error);
    } finally {
      this.state.isLoadingUpdate = false;
    }
  }
}

LLMThreadHeader.props = {
  thread: { type: Object, optional: true },
};
