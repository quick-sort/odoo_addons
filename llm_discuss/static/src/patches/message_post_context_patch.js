/** @odoo-module **/

import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    async doMessagePost(params, tmpMessage) {
        const llmDiscuss = this.env.services["llm.discuss"];
        const thread =
            tmpMessage?.thread ||
            this.Thread.get({
                model: params.thread_model,
                id: params.thread_id,
            });
        if (
            params.thread_model === "discuss.channel" &&
            llmDiscuss?.isAssistantThread(thread) &&
            !params.context?.llm_discuss_page_context
        ) {
            const pageContext = llmDiscuss.getPageContext();
            if (Object.keys(pageContext).length) {
                params = {
                    ...params,
                    context: {
                        ...params.context,
                        llm_discuss_page_context: pageContext,
                    },
                };
            }
        }
        return super.doMessagePost(params, tmpMessage);
    },
});
