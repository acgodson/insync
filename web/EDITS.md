# Web UI edits for InSync (web/dist/index.html)

Edited the built single file `web/dist/index.html`. The untouched original is `web/dist/index.original.html`
(`diff web/dist/index.original.html web/dist/index.html` shows everything). Every edit below is a literal
find/replace that matched exactly once, so it can be applied to the Vite source the same way. Almost all of them
are in the app script (the last inline `<script>`, the `(function () { "use strict"; var $ = ...` IIFE, the
`main` / app module in source). H1 is in the HTML markup. The mock module (`mock.ts`, `AlmeroMock`) is **not modified**.

Offsets are character offsets (Python `str.find`, the file is UTF-8 with non-ASCII chars, so they are not byte
offsets past the first non-ASCII char) of the old snippet in `index.original.html`, and of the new snippet in `index.html` right after the J/H edits (the K follow-up edits below shift later offsets; search by snippet).

## How the transport is picked (`createSocket()`, edit J12)

1. **InSync bridge**: `window.insync && window.insync.native === true` -> `send(str)` calls `window.insync.send(str)`,
   service messages arrive through `window.insync.onMessage = (json) => socket.onmessage({data: json})`, and
   `onopen` fires right away (deferred one tick so the page has set its handlers). If the bridge is not there when the
   script runs, the page waits up to 500 ms for `window` event `insync-ready`.
2. **Real WebSocket**: no bridge, and the URL has `?service=ws://host:port/ws` or `?mock=0`. Without `service` the URL is
   `ws(s)://<location.host>/ws?room=<?room=>&role=signer`. It reconnects every 2 s after a close; `ui_ready` is re-sent on every open.
3. **Mock**: otherwise, `AlmeroMock.connect({ autoplay: false })` exactly as before (standalone demo).

Callbacks the page puts on the bridge (`onMessage`, `speechResult`, `voices`) are kept in `bridgeHandlers` and
re-attached on every `insync-ready`, because the app injects `window.insync` twice (page start and page finish) and a
fresh object would lose them.

The wrapper keeps the mock-only methods the demo UI calls (`teacherSays`, `aliceSigns`, `knows`, `learnNow`,
`setAutoplay`, `pause`, `resume`, `restart`, `setSpeed`). With the mock they delegate to it. Otherwise they do nothing, except:
`teacherSays(text)` sends `speech_text {text}` and `learnNow(label)` sends `teach_stop {label}`.

## Notes / left as is

- **Voices**: done. `window.insync.voices(list)` (list of `{name, locale}`, array or JSON string) replaces the
  picker's list, English locales only, same as the browser path. The bridge's `speak(text)` has no voice argument, so the chosen
  voice is only reported to the service in `settings {language, voice}`. That message is sent on connect and when a voice is picked;
  `language` is mapped `nsl->nsl`, `asl->ase`, `bsl->bfi`. If the app wants to use the chosen voice, it has to read
  that settings message in `insync.send` or add a voice argument to `speak`. The voice list only shows if the app calls
  `voices()` after the page script has run, for example after page finish or on `insync-ready`.
- **Teaching off the mock** follows the follow-up edits K1 to K14 below. Signs are always taught through the service: live takes use `teach_start`,
  uploads go over HTTP, and there is no browser camera. On the mock, teaching works as before.
- `ui_ready` sends `view: "phone"` when the bridge is present, and `"projector"` otherwise (K14).
- Not renamed: the `AlmeroMock` global, the `almero.*` localStorage keys (renaming them would reset saved prefs) and
  code comments (CSS header comment, mock.ts header). There are no other "Almero" strings left in the file.
- The mock's own `session` handling is unchanged. The page's 2-minute idle auto-pause (the "Nothing happened for 2
  minutes, so the glasses' camera and mics turned off to save battery" text) can only fire with the mock (J6).

## Verification

- `html.parser` parses the file. All 6 inline scripts pass `node --check` (v23.7.0).
- Headless Chrome smoke tests with a fake `window.insync`, run on scratch copies:
  - **Bridge defined before the scripts run, and bridge arriving 250 ms later with `insync-ready`**: both send `ui_ready` and
    `settings`. Read aloud makes `sentence` call `insync.speak`. The mic button calls `insync.listen`, and `speechResult('good morning')`
    sends `speech_text`. The pause button sends `session {paused}` and calls `insync.setSession('paused')`. `room` shows
    "Room ABC123 · 2 people". The Demo controls menu entry is hidden and pressing D does nothing.
  - **Mock**: typed text produces the mock caption, and pressing D opens the demo drawer as before.

## Edits
### H1: Room code + participant count, small text in the top bar (hidden until a `room` message arrives)

Original offset 61778, new offset 61778.

Old:
```js
<span class="status" id="statusPill" role="status">
```
New:
```js
<span id="roomInfo" hidden style="font-family:var(--f-mono);font-size:11px;color:var(--muted);white-space:nowrap;margin-right:4px"></span>
      <span class="status" id="statusPill" role="status">
```
### J1: InSync native bridge helpers: detect window.insync, keep page-defined callbacks (onMessage, speechResult, voices) attached even when the app re-injects the bridge on page finish

Original offset 4736965, new offset 4737110.

Old:
```js
  // ======================================================== app
  var NAMES = { bob: "Teacher", alice: "Alice" };
```
New:
```js
  // ======================================================== app
  // ---------- InSync app bridge (Flutter WebView). window.insync is injected on page start and
  // again on page finish, followed by an 'insync-ready' event. Callbacks the page defines on it
  // (onMessage, speechResult, voices) live in bridgeHandlers and are re-attached on every inject.
  function insyncBridge() { var b = window.insync; return b && b.native === true ? b : null; }
  var bridgeHandlers = {};
  function attachBridge() { var b = insyncBridge(); if (!b) return null; for (var k in bridgeHandlers) b[k] = bridgeHandlers[k]; return b; }
  window.addEventListener("insync-ready", function () { attachBridge(); });
  var NAMES = { bob: "Teacher", alice: "Alice" };
```
### J2: Declare nativeVoices flag (true once the app sends its TTS voice list)

Original offset 4742480, new offset 4743257.

Old:
```js
  var voices = [];
  function loadVoices() {
    if (!canSpeak) return;
```
New:
```js
  var voices = [], nativeVoices = false;
  function loadVoices() {
    if (!canSpeak || nativeVoices) return;
```
### J3: Native TTS: sayWith() speaks through window.insync.speak(text) when the bridge is present (speechSynthesis stays the fallback). Native voice list: window.insync.voices(list) fills the voice picker. settings {language, voice} is sent to the service when a voice is picked and on connect.

Original offset 4743446, new offset 4744261.

Old:
```js
  function sayWith(text, v) {
    if (!canSpeak) return;
```
New:
```js
  bridgeHandlers.voices = function (list) {
    try { if (typeof list === "string") list = JSON.parse(list); } catch (e) { return; }
    if (!Array.isArray(list)) return;
    nativeVoices = true; canSpeak = true;
    voices = list.map(function (x) { var l = String((x && x.locale) || "").replace("_", "-"); return { name: String((x && x.name) || l), lang: l, voiceURI: "native:" + ((x && x.name) || l), native: true }; })
      .filter(function (v) { return /^en/i.test(v.lang); });
    voices.sort(function (a, b) { return accentOf(a).localeCompare(accentOf(b)) || a.name.localeCompare(b.name); });
    renderVoice(); if (!$("persScrim").hidden) renderPers(); if ($("onbVoices")) renderVoiceList($("onbVoices"));
  };
  var LANG_CODES = { nsl: "nsl", asl: "ase", bsl: "bfi" };
  function sendSettings() { if (!socket) return; var v = chosenVoice(); sendUi({ type: "settings", language: LANG_CODES[lang] || lang, voice: v ? v.name : "" }); }
  function sayWith(text, v) {
    var nb = insyncBridge(); if (nb) { try { nb.speak(text); } catch (e) {} return; }
    if (!canSpeak) return;
```
### J4: Send settings {language, voice} when the signer picks a voice

Original offset 4744535, new offset 4746378.

Old:
```js
prefs.voice = v.voiceURI; store.set("almero.voice", v.voiceURI); sayWith(
```
New:
```js
prefs.voice = v.voiceURI; store.set("almero.voice", v.voiceURI); sendSettings(); sayWith(
```
### J5: Session pause/resume also tells the native app via window.insync.setSession(state) (session {state} is still sent to the socket)

Original offset 4752056, new offset 4753915.

Old:
```js
live = on; touch(); if (on) liveSince = performance.now(); sendUi({ type: "session", state: on ? "live" : "paused" });
```
New:
```js
live = on; touch(); if (on) liveSince = performance.now(); sendUi({ type: "session", state: on ? "live" : "paused" });
    var nbs = insyncBridge(); if (nbs) try { nbs.setSession(on ? "live" : "paused"); } catch (e) {}
```
### J6: Idle auto-pause ('Nothing happened for 2 minutes ... save battery') only runs with the mock; with the bridge or a real socket the app/service owns power management

Original offset 4752925, new offset 4754884.

Old:
```js
if (live && idleLimit && !demo &&
```
New:
```js
if (socket && socket.isMock() && live && idleLimit && !demo &&
```
### J7: Mic button: with the bridge, start/stop native speech-to-text (window.insync.listen / stopListening) instead of the browser SpeechRecognition

Original offset 4753681, new offset 4755669.

Old:
```js
  $("micBtn").addEventListener("click", function () {
    if (listening && rec) {
```
New:
```js
  $("micBtn").addEventListener("click", function () {
    var nb = insyncBridge();
    if (nb) {
      if (listening) { try { nb.stopListening(); } catch (e) {} setMic(false); return; }
      try { nb.listen(); setMic(true); } catch (e) { setMic(false); micUnavailable(); }
      return;
    }
    if (listening && rec) {
```
### J8: Native STT result: window.insync.speechResult(text) goes through the same teacherSay() path as the browser mic (mock: teacherSays; bridge/real socket: speech_text {text})

Original offset 4754873, new offset 4757101.

Old:
```js
  function teacherSay(t, source) { t = t.trim(); if (!t) return; touch(); socket.teacherSays(t, source || "typed"); }
```
New:
```js
  function teacherSay(t, source) { t = t.trim(); if (!t) return; touch(); socket.teacherSays(t, source || "typed"); }
  bridgeHandlers.speechResult = function (text) { setMic(false); var t = String(text == null ? "" : text).trim(); if (t) { $("sayText").value = ""; teacherSay(t, "device"); } };
```
### J9: Handle `room {code, participants}`: show code + participant count in the top bar

Original offset 4788085, new offset 4790491.

Old:
```js
      case "status": $("conn").textContent
```
New:
```js
      case "room":
        var ri = $("roomInfo"), np = (m.participants || []).length;
        ri.textContent = "Room " + m.code + " · " + np + (np === 1 ? " person" : " people"); ri.hidden = false;
        break;
      case "status": $("conn").textContent
```
### J10: Tour: the 'pauses itself after 2 quiet minutes' sentence only shows with the mock

Original offset 4802503, new offset 4805123.

Old:
```js
It also pauses itself after 2 quiet minutes." },
```
New:
```js
", mock: " It also pauses itself after 2 quiet minutes." },
```
### J11: Tour: append mock-only text

Original offset 4803683, new offset 4806314.

Old:
```js
tip.appendChild(el("h4", null, step.t)); tip.appendChild(el("p", null, step.d));
```
New:
```js
tip.appendChild(el("h4", null, step.t)); tip.appendChild(el("p", null, step.d + (step.mock && socket && socket.isMock() ? step.mock : "")));
```
### J12: Transport: createSocket() picks (a) the InSync bridge, (b) a real WebSocket when ?service=... or ?mock=0, (c) the existing mock. Same onopen/onmessage/onreset handling; also sends settings on connect and hides demo leftovers when not on the mock

Original offset 4805929, new offset 4808620.

Old:
```js
  var socket = AlmeroMock.connect({ autoplay: false });
  socket.onopen = function () { sendUi({ type: "ui_ready", view: "projector" }); };
```
New:
```js
  // Transport. Returns a socket-like object {send(str), onopen, onmessage, onclose, onreset, close()}.
  //  (a) InSync app bridge present (window.insync.native) -> send() = insync.send, incoming via insync.onMessage
  //  (b) else ?service=ws://host:port/ws or ?mock=0 -> real WebSocket
  //      (default ws(s)://<location.host>/ws?room=<?room=>&role=signer)
  //  (c) else the built-in mock, exactly as before (standalone demo)
  // If the bridge is not there yet, wait up to 500 ms for 'insync-ready' before falling back.
  // The mock-only helpers (aliceSigns, knows, setAutoplay...) are no-ops off the mock; teacherSays
  // becomes speech_text {text}.
  function createSocket() {
    var q = new URLSearchParams(location.search), queue = [], inner = null, closed = false;
    var svc = q.get("service"), wantWs = !!svc || q.get("mock") === "0";
    var wsUrl = svc || ((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws?room=" + encodeURIComponent(q.get("room") || "") + "&role=signer");
    function mock() { return sock.mode === "mock" ? inner : null; }
    var sock = {
      mode: "pending", readyState: 0, onopen: null, onmessage: null, onclose: null, onreset: null, onmode: null,
      isMock: function () { return sock.mode === "mock"; },
      send: function (str) {
        if (typeof str !== "string") str = JSON.stringify(str);
        if (sock.mode === "bridge") { var b = insyncBridge(); if (b) try { b.send(str); } catch (e) {} return; }
        if (inner && inner.readyState === 1) inner.send(str); else queue.push(str);
      },
      close: function () { closed = true; sock.readyState = 3; if (inner && inner.close) inner.close(); },
      teacherSays: function (text, source) { if (mock()) return mock().teacherSays(text, source); sock.send(JSON.stringify({ type: "speech_text", text: text, ts: Date.now() })); },
      aliceSigns: function (g) { if (mock()) mock().aliceSigns(g); },
      knows: function (g) { return mock() ? mock().knows(g) : false; },
      learnNow: function (label) { if (mock()) return mock().learnNow(label); if (label) sock.send(JSON.stringify({ type: "teach_stop", label: label, ts: Date.now() })); },
      setAutoplay: function (on) { if (mock()) mock().setAutoplay(on); },
      pause: function () { if (mock()) mock().pause(); },
      resume: function () { if (mock()) mock().resume(); },
      restart: function () { if (mock()) mock().restart(); },
      setSpeed: function (x) { if (mock()) mock().setSpeed(x); }
    };
    function opened() {
      sock.readyState = 1; var p = queue; queue = [];
      if (sock.onopen) sock.onopen();
      p.forEach(function (x) { sock.send(x); });
    }
    function incoming(e) { if (sock.onmessage) sock.onmessage(e); }
    function connectWs() {
      var ws; try { ws = new WebSocket(wsUrl); } catch (e) { if (!closed) setTimeout(connectWs, 2000); return; }
      inner = ws; ws.onopen = opened; ws.onmessage = incoming;
      ws.onclose = function () { sock.readyState = 3; if (sock.onclose) sock.onclose(); if (!closed) setTimeout(connectWs, 2000); };
    }
    function decide(mode) {
      if (sock.mode !== "pending") return;
      sock.mode = mode;
      if (mode === "bridge") {
        bridgeHandlers.onMessage = function (json) { incoming({ data: typeof json === "string" ? json : JSON.stringify(json) }); };
        attachBridge(); opened();
      } else if (mode === "ws") connectWs();
      else {
        inner = AlmeroMock.connect({ autoplay: false });
        inner.onopen = opened; inner.onmessage = incoming;
        inner.onreset = function () { if (sock.onreset) sock.onreset(); };
      }
      if (sock.onmode) sock.onmode(mode);
    }
    if (insyncBridge()) setTimeout(function () { decide("bridge"); }, 0);
    else {
      var onReady = function () { if (insyncBridge()) { window.removeEventListener("insync-ready", onReady); decide("bridge"); } };
      window.addEventListener("insync-ready", onReady);
      setTimeout(function () { window.removeEventListener("insync-ready", onReady); decide(wantWs ? "ws" : "mock"); }, 500);
    }
    return sock;
  }
  var socket = createSocket();
  socket.onopen = function () { sendUi({ type: "ui_ready", view: "projector" }); sendSettings(); };
  socket.onmode = function (mode) {
    if (mode === "mock") return;
    // demo leftovers belong to the mock only: hide the drawer and its menu entry
    toggleDrawer(false);
    var md = $("mDemo"); md.hidden = true; if (md.previousElementSibling && md.previousElementSibling.tagName === "HR") md.previousElementSibling.hidden = true;
    if (insyncBridge()) { canSpeak = true; renderVoice(); }
    refreshSignBtns();
  };
```
### J13: Press D (demo drawer) only works with the mock

Original offset 4807915, new offset 4815133.

Old:
```js
if ((e.key === "d" || e.key === "D") && !/INPUT|TEXTAREA/.test(tag)
```
New:
```js
if ((e.key === "d" || e.key === "D") && socket.isMock() && !/INPUT|TEXTAREA/.test(tag)
```
## Rename Almero -> InSync (visible strings)

Applied as regex `Almero(?!Mock)` -> `InSync` to the `<title>`, the body markup and the app script. The strings are the same length, so the offsets are the same in both files.

| # | where | offset | context (original) |
|---|---|---|---|
| 1 | title | 118 | `<title>Almero` |
| 2 | body markup | 61381 | `stroke-linecap="round" stroke-linejoin="round"/></svg><span>Almero</span></div>       <div class="tabs" role="tablist" a` |
| 3 | body markup | 62809 | `on" id="mIntro"><svg class="i"><use href="#book"/></svg>How Almero works</button>       <button role="menuitem" type="bu` |
| 4 | body markup | 66769 | `b">             <div class="libhd"><div><h2>My signs</h2><p>Almero understands these and can sign them back</p></div><bu` |
| 5 | body markup | 68581 | `dden role="dialog" aria-modal="true" aria-label="Welcome to Almero" tabindex="-1">       <div class="onb-top"><div class` |
| 6 | body markup | 68841 | `r="5.5" fill="var(--alice)" fill-opacity=".92"/></svg><span>Almero</span></div><button class="onb-skip" id="onbSkip" typ` |
| 7 | body markup | 70087 | `moHint">A teacher talks to Alice, she replies, then teaches Almero a new sign</div>   </div>   <div class="sbox">     <h` |
| 8 | body markup | 70288 | `s"></div>     <div class="hint">The dashed button is a sign Almero doesn't know yet</div>   </div>   <div class="sbox"> ` |
| 9 | app script | 4741051 | `o, who === "bob" ? "Teacher" : who === "alice" ? "Alice" : "Almero"));     li.appendChild(el("span", null, text)); log.i` |
| 10 | app script | 4755613 | `"The microphone isn't available here. Type instead, or open Almero in Chrome", true);     $("sayText").focus();   }   $(` |
| 11 | app script | 4756134 | ` browser can't turn speech into text. Type instead, or open Almero in Chrome");     try {       rec = new SR(); rec.lang` |
| 12 | app script | 4773956 | ` "No camera here, so this uses the glasses simulation. Open Almero in Chrome and allow the camera to record yourself."; ` |
| 13 | app script | 4791704 | `pan", null, "Checking my sign library…")]); explain("sys", "Almero compares her movement with every sign it knows and ra` |
| 14 | app script | 4792965 | `in("sys", "No guess reaches 60%. Instead of guessing wrong, Almero asks to be taught");         if (teach.state === "idl` |
| 15 | app script | 4793754 | `) + " added to My signs")]);         explain("sys", "Saved. Almero now recognises " + m.label.toUpperCase() + " and the ` |
| 16 | app script | 4796954 | `d be understood"));       left.appendChild(el("p", "lead", "Almero turns your signs into speech, and other people's spee` |
| 17 | app script | 4797403 | `);       [["hand", "You sign", "The glasses see your hands. Almero says it out loud for the other person.", "who-a"],   ` |
| 18 | app script | 4797629 | `"plus", "Teach it new signs", "Names, places, school words. Almero learns from you and gets better each time.", ""]].for` |
| 19 | app script | 4799597 | `age do you use?"));       left.appendChild(el("p", "lead", "Almero recognises your signs and signs back in the same lang` |
| 20 | app script | 4801216 | `"));       left.appendChild(el("p", "lead", "Pick the voice Almero uses when it says your signs out loud, and the interp` |
| 21 | app script | 4801945 | `pendChild(el("p", "lead", "Hold your phone in front of you. Almero maps your face once, so it knows where your chin, ear` |
| 22 | app script | 4804945 | `Your hands, live", d: "What the glasses see. When you sign, Almero shows what it read here and says it out loud." },    ` |
| 23 | app script | 4814044 | `addEventListener("click", function () { if (!live) { toast("Almero is paused, so the glasses can't see Alice. Resume fir` |
| 24 | app script | 4814592 | `addEventListener("click", function () { if (!live) { toast("Almero is paused, so the glasses can't see Alice. Resume fir` |
| 25 | app script | 4816122 | `elf" : "A teacher talks to Alice, she replies, then teaches Almero a new sign";     explain("sys", demo ? "Demo started:` |

## Follow-up edits K1 to K14: teaching through the service, video upload, ui_ready view

These were applied after the J and H edits and the rename, so the "Phase-1 offset" is the character offset in the file
as it stood after those edits. To apply them to the source, apply J/H first, or just search for the old snippet. Each one is
in the app script and matched exactly once.

Behaviour off the mock (bridge or real WebSocket):
- **Add a sign / Teach it** always uses the service mode (the old "Glasses (demo)" path). The camera/glasses switch is
  hidden and the browser camera is never started. Each shutter press sends `teach_start {label}`. On `teach_progress` the page
  counts a take and shows "Take N of M recorded". If no `teach_progress` arrives within 15 s, the take is dropped with a message.
- **Save sign** (shown once all takes are in, or after an upload) sends `teach_stop {label}` and waits for `sign_learned`.
  When it arrives, the existing handler adds the sign to My signs and shows the done screen. If nothing arrives within 10 s, the dialog
  goes back to the recording step with "The service didn't confirm X. Check the connection and save again." and a warning toast.
- **Start over / Cancel** send `teach_stop {label: ""}` (unchanged code paths).
- **Upload a video instead**: POST multipart `label`, `file`, `language` (nsl/ase/bfi). The URL is
  `${window.insync.serviceBase}/teach/upload` with the bridge (trailing slashes trimmed; error if `serviceBase` is unset), or
  `${location.origin}/teach/upload` on a real WebSocket. `{ok:true}` counts as one take ("Take N recorded from your video"). Anything
  else shows "Upload failed: <error | message | detail>". If a save has only uploads and no live takes, it finishes locally without
  `teach_stop`, because the service already saved them. Mixing uploads and live takes in one save sends `teach_stop`, and the service
  then holds only the live takes; check that this is what the backend expects.
- The stage label reads "Live from the app's camera" instead of "Glasses simulation". The hand overlay still draws the service's `landmarks`.

Follow-up test results (headless Chrome, fake bridge, fake `fetch`):
- **Teach**: the page sent `ui_ready view=phone`. Pressing the shutter sent `teach_start label="lagos"`, and the fake reply
  produced "Take 1 of 2 recorded". The second take produced "Take 2 of 2 recorded" and the "LAGOS is recorded" heading, with the Save
  button and no mode switch. Save sent `teach_stop label="lagos"`, the fake `sign_learned` produced "LAGOS is in your signs",
  and the sign appeared in My signs.
- **Upload**: the page called `POST http://fake.test:8000/teach/upload` with `{label: "kano", file: kano.mp4 (6 bytes), language: "nsl"}`
  (the trailing `/` on serviceBase was trimmed). It showed "Take 1 recorded from your video". Save led to "KANO is in your signs", with no `teach_stop` sent.
- **Save timeout** (fake bridge never answers): after "Saving ABUJA…", 10 s later the dialog showed the error message and the
  "Couldn't save ABUJA" toast, and Save was available again.
- **Mock regression**: the camera/glasses mode switch is still shown, typed text still produces a caption, and D still opens the drawer.
- All 6 inline scripts still pass `node --check`.
### K1: Teach state: count of service (live) takes; timers for the service take and save round-trips

Phase-1 offset 4772759, final offset 4772808.

Old:
```js
  var teach = blankTeach();
  function blankTeach() { return { state: "idle", source: "add", label: "", take: 0, of: 2, mode: "camera", sub: "idle", takes: [], raws: [], msg: "", score: null, usedVideo: false, mirrorRaw: false }; }
```
New:
```js
  var teach = blankTeach(), saveTimer = 0, takeTimer = 0;
  function blankTeach() { return { state: "idle", source: "add", label: "", take: 0, of: 2, mode: "camera", sub: "idle", takes: [], raws: [], msg: "", score: null, usedVideo: false, mirrorRaw: false, liveTakes: 0 }; }
```
### K2: Start over / redo also resets the service take count (it already sends teach_stop {label: ""})

Phase-1 offset 4774728, final offset 4774777.

Old:
```js
    teach.takes = []; teach.raws = []; teach.take = 0; teach.score = null;
  }
```
New:
```js
    teach.takes = []; teach.raws = []; teach.take = 0; teach.score = null; teach.liveTakes = 0; clearTimeout(takeTimer);
  }
```
### K3: Off the mock, a live take is teach_start {label} and ends on teach_progress; give up after 15 s with a message instead of hanging

Phase-1 offset 4775625, final offset 4775674.

Old:
```js
      if (teach.mode === "sim" && purpose === "take") { sendUi({ type: "teach_start", label: teach.label }); return; } // ends on teach_progress
```
New:
```js
      if (teach.mode === "sim" && purpose === "take") {
        sendUi({ type: "teach_start", label: teach.label }); // ends on teach_progress
        if (!socket.isMock()) { clearTimeout(takeTimer); takeTimer = setTimeout(function () { if (teach.sub === "recording" && rec.active) { rec.active = false; stage.rec.hidden = true; setRing(0); teach.sub = "idle"; teach.msg = "No answer from the service for that take. Try again."; renderDlg(); } }, 15000); }
        return;
      }
```
### K4: Off the mock: serviceTake() counts a take on teach_progress ("Take N of M recorded"); svcUpload() POSTs a video (label, file, language) to <serviceBase>/teach/upload and counts {ok:true} as one take. uploadVideo() routes to svcUpload off the mock

Phase-1 offset 4776924, final offset 4776973.

Old:
```js
  function uploadVideo(file) {
    if (!file || teach.sub === "recording") return;
```
New:
```js
  function serviceTake(m) {
    clearTimeout(takeTimer);
    if (!studioOpen() || teach.state !== "capture") return;
    rec.active = false; stage.rec.hidden = true; setRing(0);
    if (m.of) teach.of = m.of;
    teach.liveTakes++; teach.takes.push(null); teach.raws.push([]); teach.take = teach.takes.length; teach.sub = "idle";
    teach.msg = "Take " + teach.take + " of " + teach.of + " recorded";
    explain("alice", "Take " + teach.take + " recorded by the service");
    renderDlg(); renderReadTeach();
  }
  function svcUpload(file) {
    if (!file || teach.sub === "recording" || teach.sub === "uploading") return;
    var nb = insyncBridge(), base = nb ? nb.serviceBase : location.origin;
    if (!base) { teach.msg = "Upload failed: the app hasn't set the service address"; renderDlg(); return; }
    var fd = new FormData();
    fd.append("label", teach.label); fd.append("file", file, file.name || "sign.mp4"); fd.append("language", LANG_CODES[lang] || lang);
    teach.sub = "uploading"; teach.msg = "Uploading " + (file.name || "your video") + "…"; renderDlg();
    fetch(String(base).replace(/\/+$/, "") + "/teach/upload", { method: "POST", body: fd })
      .then(function (r) { return r.json().catch(function () { return { ok: false, error: "HTTP " + r.status }; }); })
      .then(function (j) {
        teach.sub = "idle";
        if (!j || j.ok !== true) { teach.msg = "Upload failed: " + ((j && (j.error || j.message || j.detail)) || "the service said no"); renderDlg(); return; }
        teach.usedVideo = true; teach.takes.push(null); teach.raws.push([]); teach.take = teach.takes.length;
        teach.msg = "Take " + teach.take + " recorded from your video"; renderDlg(); renderReadTeach();
      })
      .catch(function (e) { teach.sub = "idle"; teach.msg = "Upload failed: " + ((e && e.message) || "network error"); renderDlg(); });
  }
  function uploadVideo(file) {
    if (!socket.isMock()) return svcUpload(file);
    if (!file || teach.sub === "recording") return;
```
### K5: Stage label off the mock: the hands come from the app's camera via the service, not a simulation

Phase-1 offset 4766133, final offset 4766133.

Old:
```js
    if (stage.src === "sim") { t = "Glasses simulation"; cls = "ok"; }
```
New:
```js
    if (stage.src === "sim") { t = socket.isMock() ? "Glasses simulation" : "Live from the app's camera"; cls = "ok"; }
```
### K6: Uploading counts as busy (disables shutter / upload while the POST runs)

Phase-1 offset 4782308, final offset 4782308.

Old:
```js
busy = teach.sub === "countdown" || teach.sub === "recording";
```
New:
```js
busy = teach.sub === "countdown" || teach.sub === "recording" || teach.sub === "uploading", svcReady = !socket.isMock() && teach.take > 0 && (teach.take >= teach.of || teach.usedVideo);
```
### K7: Off the mock, no more live takes once the service has all of them

Phase-1 offset 4785267, final offset 4785267.

Old:
```js
      sh.disabled = busy || notReady || (isTest && teach.sub === "result");
```
New:
```js
      sh.disabled = busy || notReady || (isTest && teach.sub === "result") || (!socket.isMock() && teach.take >= teach.of);
```
### K8: Heading when the takes are done off the mock

Phase-1 offset 4786230, final offset 4786230.

Old:
```js
        h(teach.take ? "Good. Sign " + L + " once more" : "Sign " + L, right);
```
New:
```js
        h(svcReady && teach.take >= teach.of ? L + " is recorded" : teach.take ? "Good. Sign " + L + " once more" : "Sign " + L, right);
```
### K9: Off the mock: hide the camera / glasses mode switch (the browser camera is never used) and offer the video upload in service mode

Phase-1 offset 4786642, final offset 4786642.

Old:
```js
        right.appendChild(seg);
        if (teach.mode === "camera") {
```
New:
```js
        if (socket.isMock()) right.appendChild(seg);
        if (teach.mode === "camera" || !socket.isMock()) {
```
### K10: Save button off the mock, once both takes are in (or after an upload)

Phase-1 offset 4787384, final offset 4787384.

Old:
```js
        r3.appendChild(btn("ghost", "Cancel", teachCancel));
```
New:
```js
        r3.appendChild(btn("ghost", "Cancel", teachCancel));
        if (svcReady) r3.appendChild(btn("act", "Save sign", teachSave, "tSave"));
```
### K11: Off the mock, new signs are always taught through the service (teach_start takes), never the browser camera

Phase-1 offset 4790856, final offset 4790856.

Old:
```js
teach.mode = demo ? "sim" : "camera";
```
New:
```js
teach.mode = demo || !socket.isMock() ? "sim" : "camera";
```
### K12: Save off the mock: teach_stop {label}, wait for sign_learned; error after 10 s instead of hanging on Saving. Uploads only (no live takes): already saved server-side, so finish locally

Phase-1 offset 4791032, final offset 4791032.

Old:
```js
  function teachSave() {
    var label = teach.label; setTeach("saving");
```
New:
```js
  function teachSave() {
    var label = teach.label;
    if (!socket.isMock()) {
      if (!teach.liveTakes) { handle({ type: "sign_learned", label: label }); return; } // uploads are saved by the service already
      setTeach("saving"); sendUi({ type: "teach_stop", label: label });
      clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        if (teach.state !== "saving") return;
        teach.msg = "The service didn't confirm " + label.toUpperCase() + ". Check the connection and save again."; setTeach("capture");
        toast("Couldn't save " + label.toUpperCase(), true);
      }, 10000);
      return;
    }
    setTeach("saving");
```
### K13: teach_progress off the mock goes to serviceTake(); sign_learned clears the save timeout

Phase-1 offset 4796502, final offset 4796502.

Old:
```js
      case "teach_progress":
        if (studioOpen() && teach.mode === "sim") finishCapture();
        break;
      case "sign_learned":
```
New:
```js
      case "teach_progress":
        if (!socket.isMock()) serviceTake(m);
        else if (studioOpen() && teach.mode === "sim") finishCapture();
        break;
      case "sign_learned":
        clearTimeout(saveTimer);
```
### K14: ui_ready view: "phone" inside the app (bridge), "projector" otherwise

Phase-1 offset 4816234, final offset 4816234.

Old:
```js
sendUi({ type: "ui_ready", view: "projector" });
```
New:
```js
sendUi({ type: "ui_ready", view: insyncBridge() ? "phone" : "projector" });
```
