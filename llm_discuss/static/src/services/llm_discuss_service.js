/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export const llmDiscussService = {
    dependencies: ["action", "mail.store", "notification", "orm"],

    async start(env, { action, "mail.store": mailStore, notification, orm }) {
        let assistants = [];
        let odoobotConfig = {};
        try {
            [assistants, odoobotConfig] = await Promise.all([
                orm.call("llm.assistant", "get_available_discuss_assistants", []),
                orm.call("llm.assistant", "get_odoobot_discuss_config", []),
            ]);
        } catch (error) {
            console.warn("Could not load Discuss assistants", error);
        }
        const botPartnerIds = new Set(
            assistants.map((assistant) => assistant.bot_partner_id)
        );
        if (odoobotConfig.bot_partner_id) {
            botPartnerIds.add(odoobotConfig.bot_partner_id);
        }

        return {
            assistants,

            isAssistantThread(thread) {
                if (!thread || thread.model !== "discuss.channel") {
                    return false;
                }
                const correspondentId = thread.correspondent?.persona?.id;
                if (botPartnerIds.has(correspondentId)) {
                    return true;
                }
                return (thread.channel_member_ids || []).some((member) =>
                    botPartnerIds.has(member.persona?.id)
                );
            },

            getPageContext() {
                const controller = action.currentController;
                if (!controller) {
                    return {};
                }
                const viewType = controller.view?.type || controller.props?.type || false;
                const context = {
                    version: 1,
                    res_model:
                        controller.props?.resModel ||
                        controller.action?.res_model ||
                        false,
                    res_id:
                        viewType === "form"
                            ? controller.currentState?.resId ||
                              controller.props?.resId ||
                              false
                            : false,
                    view_type: viewType,
                    action_id:
                        controller.config?.actionId ||
                        controller.action?.id ||
                        false,
                };
                return Object.fromEntries(
                    Object.entries(context).filter(([, value]) => value !== false && value != null)
                );
            },

            async openAssistant(assistant) {
                if (!assistant?.bot_user_id) {
                    notification.add(_t("This assistant has no Discuss bot user."), {
                        type: "warning",
                    });
                    return;
                }
                await mailStore.openChat({ userId: assistant.bot_user_id });
            },
        };
    },
};

registry.category("services").add("llm.discuss", llmDiscussService);
