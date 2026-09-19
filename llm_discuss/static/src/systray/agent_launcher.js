/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LlmAgentLauncher extends Component {
    static template = "llm_discuss.AgentLauncher";
    static components = { Dropdown, DropdownItem };
    static props = [];

    setup() {
        this.llmDiscuss = useService("llm.discuss");
    }

    openAgent(agent) {
        return this.llmDiscuss.openAgent(agent);
    }
}

registry.category("systray").add(
    "llm_discuss.AgentLauncher",
    { Component: LlmAgentLauncher },
    { sequence: 25 }
);
