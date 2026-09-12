# LLM Discuss Live Chat

Companion module for [`llm_discuss`](../llm_discuss): lets an assistant act as
a website **Live Chat operator**.

**Module Type:** Bridge (`llm_discuss` ⇄ `im_livechat`)

## What it does

- Adds **Live Chat Channels** to `llm.assistant`.
- Keeps the current bot user's operator membership synchronized, including
  removing an old bot when the user is replaced, cleared, or the assistant is
  deleted.
- Replies to visitor comments when the assistant bot is the session's assigned
  operator; no `@mention` is required.
- Reuses `llm_discuss`'s fenced asynchronous queue, native typing indicator,
  complete non-streaming reply, and final native `discuss.channel` message.

Website guests do not have an internal execution user. Their jobs use the
assistant's dedicated low-privilege bot user rather than sudo. The queue marks
this service-user mode when the message is accepted and revalidates that the
same bot is still the session operator before generation, final reply, or
failure notice. Reassignment therefore revokes pending bot work. Only
explicitly safe tools should be enabled for visitor-facing assistants.

## Install

```bash
odoo-bin -d your_db -i llm_discuss_livechat
```

See [`DESIGN.md`](DESIGN.md) for operator routing and security limitations.

## License

LGPL-3
