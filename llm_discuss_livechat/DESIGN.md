# LLM Discuss Live Chat — Design Document

Status: implemented (v19.0.3.0.0)
Depends on: `llm_discuss` (see its `docs/design.md` for the base architecture),
`im_livechat`

## 1. Problem

`llm_discuss` makes an agent answer in ordinary Discuss chats/channels,
but `im_livechat` sessions are a distinct `discuss.channel_type = 'livechat'`
with their own operator-assignment model (`im_livechat.channel.user_ids`).
Live Chat's operator-selection logic
(`im_livechat.channel._get_operator()` / `_get_operator_info()`, in Odoo
core) only ever considers **real, non-share `res.users`** as candidate
operators — a portal/public identity cannot be an operator. This module lets
the `llm_discuss` bot account (already a plain internal `res.users`) be
registered as an operator on one or more Live Chat channels, and adds the
Live-Chat-specific auto-reply rule.

## 2. What this module adds, concretely

1. A `livechat_channel_ids` (`im_livechat.channel`, Many2many) field on
   `llm.agent`: which Live Chat channels this agent operates in.
2. On write, the agent's `discuss_user_id` is added to
   `im_livechat.channel.user_ids` for every channel in
   `livechat_channel_ids` (and removed from channels no longer selected) —
   see `_sync_livechat_operator()`.
3. An override of `discuss.channel._llm_discuss_should_trigger()` (defined
   in `llm_discuss`) that adds one more condition: *any* comment message in
   a `channel_type == 'livechat'` session where `livechat_operator_id`
   is this agent's bot partner triggers a reply — no `@mention` or
   1:1-chat check needed, because in a Live Chat session there is exactly
   one visitor and one operator, so every visitor message is implicitly
   "addressed" to the operator.

The module reuses `llm_discuss`'s fenced async queue, native bot typing,
explicit `stream=False`, and one-message final reply. Because website guests do
not have an internal execution identity, visitor jobs persist an
`assistant_user` execution mode and run hidden threads/tools as the dedicated
low-privilege bot user, never as sudo. The queue revalidates that this bot is
still `livechat_operator_id` before generation and again before any final or
failure post; assigning another operator therefore revokes pending work. Only
explicitly safe tools should be enabled on visitor-facing agents.

Operator synchronization also removes the previous bot user when
`discuss_user_id` is replaced or cleared, and removes memberships when the
agent is deleted.

## 3. Operator selection interaction

Odoo core's `im_livechat.channel._get_operator()` load-balances between
*all* candidate operators of a channel (least busy, matching language,
etc. — see `addons/im_livechat/models/im_livechat_channel.py`). If a Live
Chat channel has both human agents and an LLM bot operator in `user_ids`,
**visitors may be randomly routed to either** — this module does not special
-case "always prefer the bot" or "always prefer a human". If you want the
bot to be the *only* responder for a given Live Chat channel, put only the
bot account in that channel's `user_ids` (i.e. `livechat_channel_ids` should
be the only member list for that `im_livechat.channel`); if you want a
"bot-first, escalate to human" flow, use Odoo's native `chatbot.script`
mechanism instead (`im_livechat`'s own bot framework, with its
`is_forward_operator` step type) rather than this module — they solve
different problems and are not mutually exclusive.

## 4. Why not just make every `discuss_enabled` agent a livechat trigger unconditionally

Because `llm_discuss` has no dependency on `im_livechat` and must not break
when that module isn't installed — `discuss.channel.livechat_operator_id`
and `channel_type == 'livechat'` only exist once `im_livechat` (and thus
this module) is installed. Keeping the livechat-specific condition in a
separate `_inherit` of `_llm_discuss_should_trigger()`, shipped by a
separate addon that depends on both, keeps `llm_discuss` installable on its
own.

## 5. Limitations

- No RTC (voice/video) support — the bot obviously cannot join a call; if a
  visitor starts a call, Odoo core's own RTC invite logic runs unaffected
  and simply won't be answered by the bot.
- No transcript/rating awareness — the bot does not read `livechat_status`
  or react to `feedback`; it only answers messages.
- Session assignment happens through the same `_get_operator()` load
  balancer as human agents (§3); this module does not add a "prefer bot"
  weighting.
- Same conversation-history limitation as `llm_discuss` (see its
  `docs/design.md`): each visitor message is answered independently.

## 6. Module layout

```
llm_discuss_livechat/
├── __manifest__.py
├── models/
│   ├── llm_agent.py     # livechat_channel_ids + operator sync
│   └── discuss_channel.py   # _llm_discuss_should_trigger override
├── views/llm_agent_views.xml   # adds the field to llm_discuss's "Discuss" tab
└── DESIGN.md                # this file
```
