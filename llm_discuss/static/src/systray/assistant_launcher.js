/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LlmAssistantLauncher extends Component {
    static template = "llm_discuss.AssistantLauncher";
    static components = { Dropdown, DropdownItem };
    static props = [];

    setup() {
        this.llmDiscuss = useService("llm.discuss");
    }

    openAssistant(assistant) {
        return this.llmDiscuss.openAssistant(assistant);
    }
}

registry.category("systray").add(
    "llm_discuss.AssistantLauncher",
    { Component: LlmAssistantLauncher },
    { sequence: 25 }
);
