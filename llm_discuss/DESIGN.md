# LLM Discuss — Design

Status: implemented (`19.0.3.0.0`)

Related module: `llm_discuss_livechat` (optional website Live Chat bridge)

## 1. Native Odoo integration

The user-facing conversation is always a native `discuss.channel`. The module
does not render a parallel LLM chat UI and does not modify Odoo core.

```text
Composer / ChatWindow
    -> Thread.post()
    -> /mail/message/post
    -> discuss.channel.message_post()
    -> llm.discuss.reply.queue
    -> llm.assistant (non-streaming)
    -> discuss.channel.message_post(reply persona)
    -> discuss.channel/new_message bus
    -> Mail Store / Discuss / floating ChatWindow
```

Dedicated assistants use `mail.store.openChat({ userId: botUserId })` from the
systray launcher. Odoo creates or reuses the canonical 1:1 channel and selects
the correct native UI for desktop, Discuss, or mobile.

One assistant may instead use the existing `base.partner_root` OdooBot persona.
No OdooBot user is assigned to the assistant and no core record is replaced.

## 2. Triggering, OdooBot takeover, and queueing

`discuss.channel._message_post_after_hook()` evaluates enabled dedicated bots.
Base trigger modes are direct chat, explicit mention, or both. Bot-authored and
non-comment messages are ignored.

For OdooBot, the hook captures takeover eligibility **before** calling
`super()`. This matters because the last onboarding message changes the user's
`odoobot_state` from `onboarding_canned` to `idle`; that message must receive
only Odoo's final tutorial answer, not a duplicate LLM answer.

The takeover requires all of the following:

- one active assistant has **Use for OdooBot Private Chat** enabled;
- the sender is an internal user allowed to use that assistant;
- the sender's `odoobot_state` is `idle` or `disabled`;
- the channel is a true 1:1 chat containing only that user and
  `base.partner_root`;
- the message is a user-authored comment.

An inherited `mail.bot._apply_logic()` suppresses only native idle/disabled
canned replies when those conditions hold. It delegates all onboarding states,
the plain-text `start the tour` restart, and explicit commands such as `/help`
to core `mail_bot`. The message captured as pre-onboarding is never queued even
if core changes the state to `idle` during the same hook.

A matching message creates one queue row per `(assistant, source message)`.
`reply_partner_id` persists the visible author/typing persona independently of
the execution user. The unique constraint is wrapped in a savepoint so a
concurrent duplicate cannot abort the user's message transaction.

The worker:

1. claims one pending row with `FOR UPDATE SKIP LOCKED`;
2. assigns a random fencing token and commits the claim;
3. publishes native typing for `reply_partner_id`;
4. invokes the assistant with `stream=False`;
5. locks the row and verifies the fencing token;
6. posts one complete message as the persisted reply partner and marks done;
7. commits state, then clears that persona's typing when no matching job remains.

Jobs older than the processing timeout are fenced and marked failed. They are
not replayed automatically because a tool may have an external side effect.

## 3. Execution identity and sudo boundary

For internal users, the queue stores the sender, active company, and immutable
`source_user` execution mode at post time, then binds the assistant with:

```python
assistant.with_user(source_user).with_company(source_company)
```

The hidden `llm.thread`, its messages, related-record reads, and all tools use
the sender's ACLs, record rules, and company rules. The hidden thread owner is
that execution user. `reply_partner_id` never participates in authorization;
in particular, displaying `base.partner_root` does not grant root permissions.

Provider/model credentials are read through a narrow sudo scope. The final
native reply uses narrow `channel.sudo().message_post(author_id=reply_partner)`
because cron must publish as another persona. Neither sudo recordset is passed
to tools.

The public `llm.assistant.invoke()` accepts neither an arbitrary execution user
nor system-role background. Discuss uses a private server-side entry only after
assistant availability is checked.

For website guests, no internal source user exists; the Live Chat bridge
persists an `assistant_user` mode and falls back to the assistant's dedicated
low-privilege service user, never sudo. Service-user mode is rejected outside a
Live Chat channel. If an internal source user is removed, deactivated, or loses
internal status before processing, the job fails closed instead of changing
execution principal.

## 4. Page context

Immediately before `/mail/message/post`, a patch of `Store.doMessagePost()`
checks whether the channel contains a permitted dedicated bot or the OdooBot
persona for a permitted takeover assistant, then captures the Action Controller:

```json
{
  "version": 1,
  "res_model": "sale.order",
  "res_id": 42,
  "view_type": "form",
  "action_id": 123
}
```

The snapshot is placed in `context.llm_discuss_page_context`, not `post_data`
(which is restricted by the core mail route). It is captured for every send,
so a floating window follows page changes. Non-form views omit `res_id`.

The server validates model, ID, view type, and record read access when the job
is created. The worker checks again under the final execution user/company.
Only metadata and `display_name` enter the LLM background. JSON is marked as
untrusted reference data and angle brackets are escaped in the system message.

Do not add arbitrary action context, domains, or unrestricted record fields.
Richer context must use an explicit allowlist and the same execution user.

## 5. Non-streaming generation and native waiting

Discuss passes `stream=False` through every assistant round, including rounds
after tool calls. Independent `llm.thread` SSE usage keeps its existing default.
The actual final assistant message becomes the channel reply; errors and tool
messages are not mistaken for the answer.

The queue calls the reply persona channel member's native
`_notify_typing(True/False)`. This uses the standard indicator in Discuss and
floating ChatWindow and creates no temporary “Thinking...” message.

Typing is cleared only after queue state commits and no other active job exists
for the same assistant, channel, and effective reply persona.

## 6. Assistant availability and singleton configuration

Dedicated launchers and ordinary channels respect `is_public` and
`allowed_group_ids`. OdooBot takeover checks the same rules for each sender.
The frontend receives only safe bot/user/partner IDs; provider details and
credentials are not exposed.

A hidden nullable key with a database unique constraint backs
`odoobot_enabled`, so concurrent writes cannot configure two takeover
assistants. Multiple disabled assistants keep a null key and remain valid.

Queue rows are accessible only to `llm.group_llm_manager`. They retain page
references and internal error details for seven days, then cron removes them.

## 7. Current limitations

- Each source message creates a separate hidden thread; channel history is not
  replayed as multi-turn context.
- Page context contains only record identity and display name by default.
- Failed jobs require a new user message/manual retry; automatic replay is
  deliberately disabled for tool safety.
- Native typing expires client-side for unusually long calls.
- OdooBot takeover is internal-user-only and does not replace Odoo's website
  Live Chat chatbot framework.

## 8. Layout

```text
llm_discuss/
├── models/
│   ├── llm_assistant.py
│   ├── discuss_channel.py
│   ├── mail_bot.py
│   └── llm_discuss_reply_queue.py
├── static/src/
│   ├── services/llm_discuss_service.js
│   ├── patches/message_post_context_patch.js
│   └── systray/assistant_launcher.{js,xml}
├── data/ir_cron_data.xml
├── security/ir.model.access.csv
└── views/llm_assistant_views.xml
```
