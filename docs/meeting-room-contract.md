# Meeting room: messages the web UI sends and expects

**For:** Dubem (integration), Martins (recognition), Ephraim (language and voice)
**Status:** what the UI in `web/` does today. It runs on a fake backend until the service speaks these. Please say yes, no or changed on each one. Every message also has `ts`, milliseconds since 1970.

The service **relays between everyone in the same room**.

## UI to service

| Message | When |
|---|---|
| `{"type":"join","room":"alm-7k2-q9p","id":"p-abc123","name":"Alice","role":"sign","photo":"data:image/jpeg;base64,…"}` | On connecting. `role` is `sign` or `speak`. `photo` is an optional still from the join screen (about 15 KB), shown on other people's tiles because there's no live video between laptops. The UI makes up `id` |
| `{"type":"state","mic":false,"cam":true,"hand":false}` | Mic, camera or raised hand changed. **New** |
| `{"type":"speaking","id":"p-abc123","on":true}` | Someone's mic gets loud or quiet. Relay it |
| `{"type":"signing","id":"p-abc123","on":true,"teaching":false}` | The signer's hands appear or drop, or they open Add a sign (`teaching`). **New.** Relay it, so hearing people see "Alice is signing. Please wait" |
| `{"type":"speech_text","text":"…","source":"speech"}` | Words from browser speech recognition, or `"source":"typed"`. **Typed by someone with role `sign`, treat it as their `sentence`** |
| `{"type":"hands","frames":[{"t_ms":0,"hands":[{"side":"right","points":[[x,y,z],…21]}]}]}` | The signer's hands, batched about every 300 ms. Points are 0 to 1 of the webcam picture. Sent while hands are tracked |
| `{"type":"session","state":"paused"}` or `"live"` | Pause Almero. Stop recognition and speech for this person. Typing still works |
| `{"type":"voice","name":"Daniel"}` | The voice this signer chose. **New.** Please copy it into `voice` on their `sentence` |
| `{"type":"teach_landmarks","label":"northumbria digital","source":"camera","takes":[[frame,…],[frame,…]]}` | Save a new sign. Same frames as `hands`. Always answer with `sign_learned` or `teach_error`; the UI gives up after 10 seconds |
| `{"type":"leave","id":"p-abc123"}` | Leaving |

## Service to UI

| Message | Who gets it |
|---|---|
| `{"type":"participants","items":[{"id":"p1","name":"Alice","role":"sign","mic":false,"cam":true,"photo":"…","hand":false}]}` | Everyone, on any change |
| `{"type":"speaking","id":"p2","on":true}` | Everyone |
| `{"type":"signing","id":"p1","on":true,"teaching":false}` | Everyone |
| `{"type":"caption","speaker":"p2","text":"…"}` | Everyone. `speaker` is a participant id. Finished sentences only |
| `{"type":"avatar_play","signs":["good","morning"]}` | Everyone, as "I speak" users have a small "What Alice sees" tile. Unknown words stay out: the UI doesn't fingerspell, and they appear in captions only |
| `{"type":"sentence","speaker":"p1","text":"Yes. What time is it?","voice":"Daniel"}` | Everyone. **Each "I speak" page speaks it aloud**, so the service shouldn't also play audio |
| `{"type":"sign_candidates","items":[{"label":"help","confidence":0.86}]}` | The signer |
| `{"type":"sign_recognized","label":"help","confidence":0.86}` | The signer |
| `{"type":"unknown_sign"}` | The signer. Shows "I don't know that sign yet" and an Add a sign button |
| `{"type":"sign_learned","label":"…"}` or `{"type":"teach_error","label":"…","reason":"…"}` | The signer, after `teach_landmarks` |
| `{"type":"leave","id":"p2"}` | Everyone |

The UI works out "Signing to Alice…" itself from the avatar, so `avatar_done` isn't needed. It ignores any message type it doesn't know.

## What I need from you
- [ ] The WebSocket URL, and how to start the service
- [ ] Which signs the avatar should expect in `avatar_play`. The labels it has movements for are in `web/src/avatar/signs.ts`, and any other label plays a generic placeholder movement
- [ ] Whether recognition can use the webcam's front view: `hands` points are filmed from the front, not from glasses
