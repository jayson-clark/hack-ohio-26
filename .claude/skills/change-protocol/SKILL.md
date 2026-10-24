---
name: change-protocol
description: Add or change a WebSocket message between the engine and UI, and regenerate the TypeScript types. Use when touching engine/protocol.py, app/src/shared/protocol.ts, or adding a new engine→UI or UI→engine message.
---

1. Edit `engine/protocol.py`. Subclass `Model` (not `BaseModel`), give the message a `type: Literal["name"] = "name"` field, and add it to `EngineMessage` (engine → UI) or `ClientMessage` (UI → engine).
2. `make types` regenerates `app/src/shared/protocol.ts`. Never hand-edit that file.
3. Engine side: handle client messages in `Engine.dispatch` (`engine/server.py`). For engine messages, broadcast `Msg(...).model_dump_json()`.
4. UI side: handle engine messages in `handleMessage` in `app/src/shared/engine.ts` (the `switch` is exhaustive on `type`). Send with `send({...})` from the same file.
5. `make test`, then commit `protocol.py` and `protocol.ts` together and tell the team.

Notes:
- Fields with defaults are still required in the generated TS (they're always serialized), so the UI has to send them.
- Binary frames are separate. The header lives in `BINARY_HEADER` (`protocol.py`) and is mirrored by hand in `app/src/shared/binary.ts`. Update both together.
- If `PROTOCOL_VERSION` matters for a breaking change, bump it. The UI gets it in `hello`.
