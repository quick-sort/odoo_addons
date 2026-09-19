# LLM Discuss

Connect `llm.agent` to Odoo's native Discuss threads and floating
ChatWindow, either through a dedicated bot user or through the existing
OdooBot private chat.

**Module Type:** Bridge (`llm` ⇄ `mail`/Discuss)

## What it does

- Creates an optional dedicated internal bot user for an agent.
- Adds an **AI Agent** systray launcher for dedicated bots. It creates or
  reuses the native 1:1 `discuss.channel` and opens Odoo's floating chat.
- Lets exactly one active agent take over each user's existing OdooBot
  private chat after native onboarding finishes. Onboarding, `start the tour`,
  and `/help` remain handled by Odoo; LLM replies keep the OdooBot name/avatar.
- Replies in dedicated direct chats and/or on `@mention`, according to the
  agent's **Reply Trigger** setting.
- Captures the active backend page (`res_model`, form `res_id`, `view_type`,
  and `action_id`) when each message is sent, including OdooBot chats. Record
  read access is checked before a minimal snapshot enters the LLM context.
- Runs asynchronously through a fenced cron-backed queue. Odoo's native typing
  indicator is shown while the request is processed.
- Forces `stream=False`; one complete native `mail.message` is posted when
  generation finishes.

## Security model

The reply persona and execution identity are intentionally separate. A reply
may appear as a dedicated bot or `base.partner_root` (OdooBot), but internal
hidden threads, page reads, and tools run as the original sender and active
company. Provider credentials and the final native post use narrow sudo scopes;
business data and tools never inherit OdooBot/root permissions.

Website Live Chat guests have no internal source user, so the companion module
uses the agent's dedicated low-privilege bot user for execution.

## Install and configure

```bash
odoo-bin -d your_db -i llm_discuss
```

Configure an agent and make it public or assign it to the intended groups.
Then choose either or both modes:

1. **Dedicated Bot User:** create its Bot User, enable Discuss, and add that
   user to the required chat/channel.
2. **OdooBot Private Chat:** enable **Use for OdooBot Private Chat**. Only one
   agent can hold this setting; no dedicated bot user is required.

For website Live Chat operator support, install `llm_discuss_livechat` too.

## Operational notes

- Failed jobs are not automatically replayed because tools may have external
  or non-idempotent side effects.
- Jobs are claimed one at a time with a fencing token. Timed-out jobs are
  marked failed rather than executed by a second worker.
- OdooBot takeover is limited to a true 1:1 chat whose members are the current
  internal user and OdooBot, and only while that user's state is `idle` or
  `disabled`.

See [`DESIGN.md`](DESIGN.md) for the detailed flow and security boundaries.

## License

LGPL-3
