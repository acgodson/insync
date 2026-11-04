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

## L: meeting-room copy, live speaker names, room line copies the join link

Product pivot (1 signer on the phone, up to ~4 participants in browsers). The mock module and the demo drawer are unchanged; L5 to L8 only change what the live (non-mock) path shows. Find by snippet.
### L1: Room line in the top bar is a button: pointer, focusable, title (tap copies the join link, L9)

Offset 61778.

Old:
```js
<span id="roomInfo" hidden style="font-family:var(--f-mono);font-size:11px;color:var(--muted);white-space:nowrap;margin-right:4px"></span>
```
New:
```js
<span id="roomInfo" hidden role="button" tabindex="0" title="Copy the join link" style="font-family:var(--f-mono);font-size:11px;color:var(--muted);white-space:nowrap;margin-right:4px;cursor:pointer"></span>
```
### L2: Settings menu header: 'You' instead of the Alice placeholder

Offset 62483.

Old:
```js
<div class="mhead"><b>Alice</b><span>Nigerian Sign Language</span></div>
```
New:
```js
<div class="mhead"><b>You</b><span>Nigerian Sign Language</span></div>
```
### L3: Settings button: user icon instead of the letter A (Alice)

Offset 62249.

Old:
```js
aria-label="Your settings"><span>A</span></button>
```
New:
```js
aria-label="Your settings"><svg class="i"><use href="#user"/></svg></button>
```
### L4: Transcript empty state: room wording (2 places: markup and the reset in JS, both replaced)

Offset 66517.

Old:
```js
Everything said in this conversation appears here
```
New:
```js
Everything said and signed in this room appears here
```
### L5: addLine() takes an optional display name (live: caption.speaker, or 'You' for the signer's sentences); the CSS class stays alice/bob

Offset 4757896.

Old:
```js
  function addLine(speaker, text) {
```
New:
```js
  function addLine(speaker, text, name) {   // name: display name off the mock (caption.speaker, or "You")
```
### L6: addLine() shows the display name when given

Offset 4758240.

Old:
```js
who.appendChild(document.createTextNode(NAMES[speaker] || speaker));
```
New:
```js
who.appendChild(document.createTextNode(name || NAMES[speaker] || speaker));
```
### L7: Off the mock, captions are styled as the hearing side and labelled with caption.speaker (participant name or 'Phone mic')

Offset 4795600.

Old:
```js
case "caption": touch(); addLine(m.speaker, m.text); explain(
```
New:
```js
case "caption": touch(); if (socket.isMock()) addLine(m.speaker, m.text); else addLine("bob", m.text, m.speaker || "Guest"); explain(
```
### L8: Off the mock, the signer's own sentences are labelled 'You'

Offset 4796997.

Old:
```js
signed = []; addLine(m.speaker, m.text); speak(m.text);
```
New:
```js
signed = []; if (socket.isMock()) addLine(m.speaker, m.text); else addLine("alice", m.text, "You"); speak(m.text);
```
### L9: Room line: 'Room CODE · N participants' (signer excluded), remembers the code for the join link

Offset 4795215.

Old:
```js
        var ri = $("roomInfo"), np = (m.participants || []).length;
        ri.textContent = "Room " + m.code + " · " + np + (np === 1 ? " person" : " people"); ri.hidden = false;
```
New:
```js
        var ri = $("roomInfo"), np = (m.participants || []).filter(function (p) { return p.role !== "signer"; }).length;
        roomCode = m.code;
        ri.textContent = "Room " + m.code + " · " + np + (np === 1 ? " participant" : " participants"); ri.hidden = false;
```
### L10: Tap (or Enter/Space) on the room line copies <serviceBase or location.origin>/join/CODE and toasts 'Link copied'

Offset 4793873.

Old:
```js
  // ======================================================== service messages
  var holoActive = false;
```
New:
```js
  // ---------- room link: tapping the room line copies <service>/join/CODE
  var roomCode = "";
  function joinLink() {
    var b = window.insync && window.insync.serviceBase;
    return String(b || location.origin).replace(/\/+$/, "") + "/join/" + roomCode;
  }
  function copyFallback(t) {
    var ta = el("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
    ta.remove(); return ok;
  }
  function copyJoinLink() {
    if (!roomCode) return;
    var link = joinLink(), done = function () { toast("Link copied"); };
    var fail = function () { if (copyFallback(link)) done(); else toast("Couldn't copy. Link: " + link, true); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(link).then(done, fail); else fail();
    // TODO(phase2): native share sheet through the bridge
  }
  $("roomInfo").addEventListener("click", copyJoinLink);
  $("roomInfo").addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copyJoinLink(); } });

  // ======================================================== service messages
  var holoActive = false;
```
### L11: Voice preview line without the Alice name

Offset 4746555.

Old:
```js
sayWith("Hi, I'm Alice. Nice to meet you.", v)
```
New:
```js
sayWith("Hi, nice to meet you.", v)
```
### L12: Read aloud toast: 'your signs' instead of Alice/her

Offset 4752403.

Old:
```js
toast(readAloud ? "Read aloud on: Alice's signs are spoken out loud" : "Read aloud off: her signs show as text only");
```
New:
```js
toast(readAloud ? "Read aloud on: your signs are spoken out loud" : "Read aloud off: your signs show as text only");
```
### L13: Onboarding welcome: the meeting-room product

Offset 4801967.

Old:
```js
"InSync turns your signs into speech, and other people's speech into signs. It works through your glasses and phone, at school, at work or at the clinic."
```
New:
```js
"InSync is your accessibility meeting room. Open the app, share the room link, and sign: everyone in the room reads your captions and hears your voice. When they talk, you read captions and your avatar signs it back."
```
### L14: Onboarding 'how': a meeting, not a classroom

Offset 4802321.

Old:
```js
      left.appendChild(el("h2", null, "How a conversation works"));
      var ul = el("ul", "howto");
      [["hand", "You sign", "The glasses see your hands. InSync says it out loud for the other person.", "who-a"],
       ["ear", "They speak", "The avatar signs their words back to you, with subtitles.", "who-b"],
       ["plus", "Teach it new signs", "Names, places, school words. InSync learns from you and gets better each time.", ""]]
```
New:
```js
      left.appendChild(el("h2", null, "How a meeting works"));
      var ul = el("ul", "howto");
      [["hand", "You sign", "Your camera sees your hands. Everyone in the room reads your captions and hears your voice.", "who-a"],
       ["ear", "They speak", "People join from any browser with your link. You read their words and your avatar signs them.", "who-b"],
       ["plus", "Teach it new signs", "Names, places, words you use often. InSync learns from you and gets better each time.", ""]]
```
### L15: Onboarding language step: 'Your sign language' (NSL / ASL / BSL)

Offset 4804615.

Old:
```js
      left.appendChild(el("h2", null, "Which sign language do you use?"));
      left.appendChild(el("p", "lead", "InSync recognises your signs and signs back in the same language."));
```
New:
```js
      left.appendChild(el("h2", null, "Your sign language"));
      left.appendChild(el("p", "lead", "NSL, ASL or BSL. InSync reads your signs in it and your avatar signs back in it."));
```
### L16: Language step illustration: MEETING instead of HOMEWORK

Offset 4805856.

Old:
```js
fill="var(--alice)">HOMEWORK</text>
```
New:
```js
fill="var(--alice)">MEETING</text>
```
### L17: Onboarding 'make it yours': the room hears the voice

Offset 4806334.

Old:
```js
"Pick the voice InSync uses when it says your signs out loud, and the interpreter that signs to you."
```
New:
```js
"Pick the voice the room hears when you sign, and the interpreter that signs to you."
```
### L18: Onboarding ready: share the link instead of 'put your glasses on'

Offset 4807880.

Old:
```js
"Put your glasses on and start talking. A quick tour shows you where everything is."
```
New:
```js
"Share the room link and start signing. A quick tour shows you where everything is."
```
### L19: Tour: room line step, meeting wording for the composer, hands view, pause and teach steps

Offset 4809841.

Old:
```js
    { el: "comp", t: "Type to sign", d: "Speech comes in through the glasses' mics. People can also type here, or use this device's mic." },
    { el: "pip", t: "Your hands, live", d: "What the glasses see. When you sign, InSync shows what it read here and says it out loud." },
    { el: "sessBtn", t: "Pause when you're done", d: "Turns off the glasses' camera and mics so they stop using battery. ", mock: " It also pauses itself after 2 quiet minutes." },
```
New:
```js
    { el: "roomInfo", t: "Your room", d: "Tap here to copy the room link. Anyone with it can join from a browser." },
    { el: "comp", t: "Type or talk", d: "Someone next to you can type here or use this phone's mic. Everyone else talks from their own browser." },
    { el: "pip", t: "Your hands, live", d: "What your camera sees. When you sign, InSync shows what it read here and sends it to the room as captions and voice." },
    { el: "sessBtn", t: "Pause when you're done", d: "Turns off the camera and mics so they stop using battery. ", mock: " It also pauses itself after 2 quiet minutes." },
```
### L20: Tour teach step: no school framing

Offset 4810585.

Old:
```js
"Record a name, a place or a school word with your camera, then test it."
```
New:
```js
"Record a name, a place or a word you use often with your camera, then test it."
```
### L21: My signs empty state: no school framing

Offset 4761820.

Old:
```js
"A name, a place, a school word. It takes about 30 seconds."
```
New:
```js
"A name, a place, a word you use often. It takes about 30 seconds."
```
### L22: Teach name step hint: no school framing

Offset 4783543.

Old:
```js
"Type the word. Names, places and school words are a good start."
```
New:
```js
"Type the word. Names, places and words you use often are a good start."
```

### L verification

- `html.parser` parses the file; all 6 inline scripts pass `node --check`. No "Almero" in markup or UI strings.
- Headless Chrome on `/app?mock=0&room=SMKE` against the local service with a participant "Bob": room line reads
  "Room SMKE · 1 participant", Bob's caption is labelled "Bob", the menu header reads "You". Tapping the room line
  builds `http://localhost:8000/join/SMKE` (headless has no clipboard, so it fell back to the "Couldn't copy. Link: ..." toast).
- Remaining "Alice"/"Teacher" text is in the mock-only demo drawer and the mock's explain() log, left as is.

## M: live browser mode (the page is the signer in any browser with a webcam)

Applied after L. Each edit is a literal find/replace that matched exactly once; offsets are character offsets of the old snippet in the file as it stood when that edit was applied (find by snippet). All in the app script.

Mode selection (`createSocket()` / `socket.onmode`):
1. `window.insync.native` -> **bridge**, unchanged (frames, socket and room come from the app; old intro if not onboarded).
2. `?mock=1` -> **mock**, the old demo and intro, unchanged.
3. Otherwise -> **live browser** (`socket.mode === "ws"`, `liveBrowser()`), the default, also at `/` and `/app` on our backend.
   The "Start your room" card (name kept in `almero.name`, sign language NSL/ASL/BSL kept in `almero.lang` and sent as nsl/ase/bfi,
   "Read my signs aloud" on by default, kept in `almero.readAloud`) replaces the intro. Start: room code from `?room=` or
   `POST ${location.origin}/rooms`, then `ws(s)://${location.host}/ws?room=CODE&role=signer&name=NAME` (reconnects every 2 s; `?service=` still overrides the URL).
   The code is written into the address bar (`?room=CODE`) so a reload rejoins the same room. On every open: `ui_ready {view: "phone"}`,
   `settings {language, voice}`, `session {state}`. Webcam (`getUserMedia`, user-facing, ideal 640x480) -> `frame {jpeg, w, h, ts}` at 10 fps
   while live and connected (frames are dropped, not queued, when the socket has more than 512 KB buffered); pause stops the track.
   The Your hands panel shows the mirrored webcam with the `landmarks` skeleton; landmarks are mapped back to the image with the
   service's own anchors (`NOSE_ANCHOR = (0.5, -0.15)`, `FACE_WIDTH = 0.30` from backend/config.py), so the overlay lines up with the hands.
   Camera denied or missing: a one-line note in the panel plus a toast; captions, voice, mic and typing keep working.
   Top bar: `Live · N participants · Room CODE` (`Paused · ...` when paused, `Connecting…` / `Reconnecting… · Room CODE` without a socket).
   Talk view: a room card (code, link, big Copy link -> `${location.origin}/join/CODE`). Mic button: browser SpeechRecognition ->
   `speech_text`, labelled "Someone next to me speaks". The glasses-mic chip is hidden. The tour only runs from the menu.
   Teaching goes through the service like the bridge (K edits): the takes come from the frames being streamed; the studio shows the
   webcam with the service's landmarks, a 3-2-1 countdown, then "Sign now… hands down to finish" until `teach_progress`.

### M1: Live browser mode block: room line with connection state, room card with a big Copy link, camera note in the Your hands panel, webcam start/stop, landmark-to-image mapping, mirrored webcam + skeleton in the panel, 10 fps frame sender, the Start your room card, startRoom(), liveSetup()

Offset 4794902. Inserted after:
```js
  $("roomInfo").addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); copyJoinLink(); } });
```
New code (appended right after it):
```js
  // ---------- live browser mode (M): no app bridge and no ?mock=1, so this page is the signer.
  // Start card -> room code from ?room= or POST /rooms -> WebSocket; webcam frames at 10 fps while live.
  function liveBrowser() { return !!socket && socket.mode === "ws"; }
  var LANG_NAMES = { nsl: "Nigerian Sign Language", asl: "American Sign Language", bsl: "British Sign Language" };
  var net = { state: "idle", np: 0 };   // idle | connecting | live | reconnecting
  function renderRoomLine() {
    if (!liveBrowser()) return;
    var ri = $("roomInfo"), code = roomCode ? "Room " + roomCode : "";
    var head = net.state === "live" ? (live ? "Live" : "Paused") + " · " + net.np + (net.np === 1 ? " participant" : " participants")
      : net.state === "reconnecting" ? "Reconnecting…" : net.state === "connecting" ? "Connecting…" : "";
    ri.textContent = [head, code].filter(Boolean).join(" · "); ri.hidden = !ri.textContent;
    ri.style.color = net.state === "live" ? "" : "var(--alice)";
    roomCard.style.display = roomCode ? "flex" : "none";
    $("roomCode").textContent = roomCode; $("roomLink").textContent = roomCode ? joinLink().replace(/^https?:\/\//, "") : "";
  }
  // room code + big Copy link, top-left of the Talk view
  var roomCard = el("div"); roomCard.id = "roomCard"; roomCard.style.cssText = "position:absolute;left:16px;top:68px;z-index:8;display:none;align-items:center;gap:14px;padding:10px 10px 10px 16px;border-radius:14px;background:#1c1d20;border:1px solid var(--line2);box-shadow:0 8px 24px rgba(0,0,0,.35);max-width:calc(100% - 140px)";
  roomCard.innerHTML = '<div style="min-width:0"><div style="font-size:12px;color:var(--muted)">Your room</div><div id="roomCode" style="font-family:var(--f-mono);font-size:24px;letter-spacing:.08em;line-height:1.15"></div><div id="roomLink" style="font-size:12px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis"></div></div>';
  var copyBig = el("button", "act", "Copy link"); copyBig.type = "button"; copyBig.id = "copyLinkBtn";
  copyBig.style.cssText = "height:48px;min-width:112px;margin:0;align-self:center;font-size:16px;border-radius:12px";
  copyBig.addEventListener("click", copyJoinLink); roomCard.appendChild(copyBig); $("conv").appendChild(roomCard);
  // one-line camera message inside the "Your hands" panel
  var pipMsg = el("div"); pipMsg.id = "pipMsg"; pipMsg.style.cssText = "position:absolute;left:8px;right:8px;top:50%;transform:translateY(-50%);text-align:center;font-size:12px;line-height:1.3;color:var(--text2);display:none";
  $("pip").appendChild(pipMsg);
  function pipNote(t) { pipMsg.textContent = t || ""; pipMsg.style.display = t ? "block" : "none"; }

  // webcam (separate from the teach studio's own camera, which stays off outside the mock)
  var cam = { stream: null, state: "off", want: false, sent: 0, video: el("video"), grab: document.createElement("canvas") };
  cam.video.muted = true; cam.video.playsInline = true; cam.video.setAttribute("playsinline", ""); cam.video.setAttribute("muted", "");
  function camReady() { return !!cam.stream && cam.video.readyState >= 2 && cam.video.videoWidth > 0; }
  function camStart() {
    cam.want = true;
    if (cam.stream || cam.state === "starting") return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { cam.state = "none"; pipNote("No camera in this browser. Captions still work."); return; }
    cam.state = "starting"; pipNote("Starting camera…");
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false }).then(function (st) {
      if (!cam.want) { st.getTracks().forEach(function (t) { t.stop(); }); cam.state = "off"; pipNote(""); return; }
      cam.stream = st; cam.state = "on"; cam.video.srcObject = st; cam.video.play().catch(function () {}); pipNote("");
      if (studioOpen() && stage.src === "sim") attachStageCam();
    }).catch(function (e) {
      cam.state = "blocked";
      pipNote(e && e.name === "NotFoundError" ? "No camera found. Captions still work." : "Camera blocked. Allow it in the browser to sign.");
      toast("InSync can't use the camera, so it can't see your signs. Captions and voice still work.", true);
    });
  }
  function camStop() {
    cam.want = false;
    if (cam.stream) cam.stream.getTracks().forEach(function (t) { t.stop(); });
    cam.stream = null; cam.video.srcObject = null;
    if (cam.state === "on" || cam.state === "starting") { cam.state = "off"; pipNote(""); }
  }
  // head-relative landmarks (x right, y up, 1 = face width, origin at the nose) back to image coords,
  // using the service's own anchors (backend config.py NOSE_ANCHOR / FACE_WIDTH)
  var NOSE = [0.5, -0.15], FACE_W = 0.30;
  function camPoint(p, vw, vh) { return { x: NOSE[0] + p[0] * FACE_W, y: NOSE[1] - p[1] * FACE_W * vw / vh, z: (p[2] || 0) * FACE_W }; }
  function drawPipCam(ctx, W, H) {
    if (!camReady() || !live) return;
    var v = cam.video, vw = v.videoWidth, vh = v.videoHeight, k = Math.max(W / vw, H / vh);
    var R = { x: (W - vw * k) / 2, y: (H - vh * k) / 2, w: vw * k, h: vh * k };
    ctx.save(); ctx.translate(W, 0); ctx.scale(-1, 1);   // mirrored, like a selfie
    ctx.drawImage(v, R.x, R.y, R.w, R.h);
    drawHands(ctx, (holo ? holo.hands : []).map(function (h) { return { pts: h.points.map(function (p) { return camPoint(p, vw, vh); }) }; }), R, Math.max(1.4, W / 140));
    ctx.restore();
  }
  // the teach studio shows the same webcam (mirrored) with the service's landmarks
  function attachStageCam() {
    if (!liveBrowser() || !cam.stream) return;
    stage.root.classList.add("mirror"); stage.video.srcObject = cam.stream; stage.video.play().catch(function () {});
  }
  // frames: 10 fps while live and connected; dropped (not queued) when the socket is backed up
  setInterval(function () {
    if (!liveBrowser() || !live || !camReady() || socket.readyState !== 1) return;
    if (socket.buffered() > 512 * 1024) return;
    var v = cam.video, k = Math.min(1, 640 / v.videoWidth), w = Math.round(v.videoWidth * k), h = Math.round(v.videoHeight * k), g = cam.grab;
    if (g.width !== w || g.height !== h) { g.width = w; g.height = h; }
    g.getContext("2d").drawImage(v, 0, 0, w, h);
    var url = g.toDataURL("image/jpeg", 0.7);
    socket.send(JSON.stringify({ type: "frame", jpeg: url.slice(url.indexOf(",") + 1), w: w, h: h, ts: Date.now() }));
    cam.sent++;
  }, 100);

  // the one "Start your room" card (replaces the multi-step intro in live browser mode)
  function openStart() {
    $("onb").hidden = false; $("onbSkip").hidden = true; $("onbFoot").textContent = "";
    var wrap = $("onbIn"); wrap.textContent = "";
    var left = el("div"), right = el("div", "vis"); right.id = "onbAvatarSlot"; right.appendChild(el("canvas"));
    left.appendChild(el("h1", null, "Start your room"));
    left.appendChild(el("p", "lead", "Sign to your camera. Everyone you share the link with reads your captions and hears your voice."));
    function lbl(text, ctl) { var l = el("label"); l.style.cssText = "display:block;margin-top:18px;font-size:14px;color:var(--text2)"; l.appendChild(el("span", null, text)); ctl.style.marginTop = "6px"; l.appendChild(ctl); left.appendChild(l); }
    var nm = el("input", "field"); nm.id = "startName"; nm.type = "text"; nm.autocomplete = "name"; nm.maxLength = 40; nm.placeholder = "e.g. Amaka"; nm.value = store.get("almero.name") || "";
    lbl("Your name", nm);
    var sel = el("select", "field"); sel.id = "startLang";
    [["nsl", "NSL · Nigerian Sign Language"], ["asl", "ASL · American Sign Language"], ["bsl", "BSL · British Sign Language"]].forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; sel.appendChild(op); });
    sel.value = LANG_NAMES[store.get("almero.lang")] ? store.get("almero.lang") : lang; lbl("Sign language", sel);
    var tg = el("label"); tg.style.cssText = "display:flex;align-items:center;gap:10px;margin-top:18px;font-size:15px;cursor:pointer";
    var cb = el("input"); cb.type = "checkbox"; cb.id = "startVoice"; cb.checked = store.get("almero.readAloud") !== "0"; cb.style.cssText = "width:20px;height:20px;margin:0;accent-color:var(--alice)";
    tg.appendChild(cb); tg.appendChild(el("span", null, "Read my signs aloud")); left.appendChild(tg);
    var a = el("div", "acts"), go = el("button", "act", "Start"); go.type = "button"; go.id = "startBtn"; a.appendChild(go); left.appendChild(a);
    go.addEventListener("click", function () { startRoom(nm.value.trim(), sel.value, cb.checked); });
    nm.addEventListener("keydown", function (e) { if (e.key === "Enter") go.click(); });
    wrap.appendChild(left); wrap.appendChild(right);
    setTimeout(function () { try { (nm.value ? go : nm).focus(); } catch (e) {} }, 30);
  }
  var started = false;
  function startRoom(name, l, aloud) {
    if (started) return; started = true;
    store.set("almero.name", name); store.set("almero.lang", l); store.set("almero.readAloud", aloud ? "1" : "0"); store.set("almero.onboarded", "1");
    lang = l; readAloud = !!aloud && canSpeak; renderVoice();
    var mh = document.querySelector("#menu .mhead"); if (mh) { mh.firstChild.textContent = name || "You"; mh.lastChild.textContent = LANG_NAMES[l] || ""; }
    $("onb").hidden = true; setTab("talk");
    net.state = "connecting"; renderRoomLine();
    if (!live) setLive(true); else camStart();
    socket.start(name).then(function (code) { if (code) roomCode = code; renderRoomLine(); });
  }
  function liveSetup() {
    $("gmic").style.display = "none";
    var mb = $("micBtn"); mb.title = micLabel(); mb.setAttribute("aria-label", micLabel());
    $("sayText").placeholder = "Someone next to me speaks: tap the mic or type"; $("sayText").setAttribute("aria-label", "Someone next to me speaks or types");
    openStart();
  }
  function micLabel() { return liveBrowser() ? "Someone next to me speaks" : "Use this device's microphone"; }
```
### M2: Your hands panel: in live browser mode draw the mirrored webcam with the skeleton on top (drawPipCam) instead of the flat glasses view

Offset 4739773.

Old:
```js
    var ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    var s = Math.min(W / 4, H / 3)
```
New:
```js
    var ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    if (liveBrowser()) { drawPipCam(ctx, W, H); return; }
    var s = Math.min(W / 4, H / 3)
```
### M3: Transport: the default is now the live WebSocket. Mock only with ?mock=1. In live mode the socket connects on start(name) (the Start button): room code from ?room=, or POST /rooms; URL /ws?room=CODE&role=signer&name=NAME (or ?service=... as is); the code is put in the address bar so a reload rejoins; POST failures retry every 2 s

Offset 4825389.

Old:
```js
        if (inner && inner.readyState === 1) inner.send(str); else queue.push(str);
      },
```
New:
```js
        if (inner && inner.readyState === 1) inner.send(str); else queue.push(str);
      },
      start: function (name) { return startLive(name); },
      buffered: function () { return (inner && inner.bufferedAmount) || 0; },
```
### M4: Transport: startLive(name) (see M3)

Offset 4826718.

Old:
```js
    function incoming(e) { if (sock.onmessage) sock.onmessage(e); }
```
New:
```js
    function incoming(e) { if (sock.onmessage) sock.onmessage(e); }
    function startLive(name) {
      var nm = encodeURIComponent(name || "");
      if (svc) { wsUrl = svc + (/[?&]name=/.test(svc) ? "" : (svc.indexOf("?") < 0 ? "?" : "&") + "name=" + nm); connectWs(); return Promise.resolve((q.get("room") || "").toUpperCase()); }
      function go(code) {
        wsUrl = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws?room=" + encodeURIComponent(code) + "&role=signer&name=" + nm;
        try { var u = new URL(location.href); if (u.searchParams.get("room") !== code) { u.searchParams.set("room", code); history.replaceState(null, "", u.toString()); } } catch (e) {}
        connectWs(); return code;
      }
      var code = (q.get("room") || "").trim().toUpperCase();
      if (code) return Promise.resolve(go(code));
      return new Promise(function (resolve) {
        (function create() {
          fetch(location.origin + "/rooms", { method: "POST" })
            .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
            .then(function (j) { if (!j || !j.code) throw new Error("no code"); resolve(go(String(j.code))); })
            .catch(function () { if (sock.onclose) sock.onclose(); if (!closed) setTimeout(create, 2000); });
        })();
      });
    }
```
### M5: Transport: ws mode waits for start() instead of connecting at once

Offset 4828700.

Old:
```js
      } else if (mode === "ws") connectWs();
```
New:
```js
      } else if (mode === "ws") { /* live browser mode: connects on sock.start(name), from the Start card */ }
```
### M6: Transport: mock only with ?mock=1; otherwise (no bridge) live browser mode

Offset 4829428.

Old:
```js
decide(wantWs ? "ws" : "mock"); }, 500);
```
New:
```js
decide(q.get("mock") === "1" ? "mock" : "ws"); }, 500);
```
### M7: ui_ready view is 'phone' whenever this is the signer (bridge or live browser); live browser mode also sends session {state} on every (re)connect and shows 'Live' in the room line; onclose shows 'Reconnecting…'

Offset 4829544.

Old:
```js
socket.onopen = function () { sendUi({ type: "ui_ready", view: insyncBridge() ? "phone" : "projector" }); sendSettings(); };
```
New:
```js
socket.onopen = function () {
    sendUi({ type: "ui_ready", view: socket.isMock() ? "projector" : "phone" }); sendSettings();
    if (liveBrowser()) { sendUi({ type: "session", state: live ? "live" : "paused" }); net.state = "live"; renderRoomLine(); }
  };
  socket.onclose = function () { if (liveBrowser() && started) { net.state = "reconnecting"; renderRoomLine(); } };
```
### M8: Onboarding: the old intro auto-opens only in mock and bridge mode (decided in onmode); live browser mode opens the Start card instead

Offset 4829919.

Old:
```js
  socket.onmode = function (mode) {
    if (mode === "mock") return;
```
New:
```js
  socket.onmode = function (mode) {
    if (mode !== "ws" && !store.get("almero.onboarded")) openOnb(0);
    if (mode === "ws") liveSetup();
    if (mode === "mock") return;
```
### M9: Onboarding no longer opens before the mode is known (moved into onmode, M8)

Offset 4836018.

Old:
```js
  resetUI();
  if (!store.get("almero.onboarded")) openOnb(0);
```
New:
```js
  resetUI();   // the intro (mock / bridge) or the Start card (live browser) opens from socket.onmode
```
### M10: Room message: keep the participant count for the live room line

Offset 4805378.

Old:
```js
        ri.textContent = "Room " + m.code + " · " + np + (np === 1 ? " participant" : " participants"); ri.hidden = false;
```
New:
```js
        ri.textContent = "Room " + m.code + " · " + np + (np === 1 ? " participant" : " participants"); ri.hidden = false;
        net.np = np; renderRoomLine();
```
### M11: Pause / resume in live browser mode releases / reacquires the webcam (frames stop with it); pause text names the camera, not the glasses

Offset 4754175.

Old:
```js
    var nbs = insyncBridge(); if (nbs) try { nbs.setSession(on ? "live" : "paused"); } catch (e) {}
```
New:
```js
    var nbs = insyncBridge(); if (nbs) try { nbs.setSession(on ? "live" : "paused"); } catch (e) {}
    if (liveBrowser() && started) { if (on) camStart(); else camStop(); }
```
### M12: Pause card text in live browser mode

Offset 4754549.

Old:
```js
        : "Glasses camera and mics are off to save battery. Typing still works";
```
New:
```js
        : liveBrowser() ? "Your camera is off, so nothing is sent. Typing still works" : "Glasses camera and mics are off to save battery. Typing still works";
```
### M13: renderSession() refreshes the live room line (Live / Paused) and names the camera on the pause button

Offset 4753648.

Old:
```js
    var g = $("gmic"); g.classList.toggle("off", !live); $("gmicLbl").textContent = live ? "Glasses mic" : "Mic off";
```
New:
```js
    var g = $("gmic"); g.classList.toggle("off", !live); $("gmicLbl").textContent = live ? "Glasses mic" : "Mic off";
    if (liveBrowser()) { b.title = live ? "Pause your camera" : "Resume your camera"; b.setAttribute("aria-label", b.title); renderRoomLine(); }
```
### M14: Mic button label in live browser mode: 'Someone next to me speaks'

Offset 4755852.

Old:
```js
b.setAttribute("aria-label", on ? "Stop listening" : "Use this device's microphone");
```
New:
```js
b.setAttribute("aria-label", on ? "Stop listening" : micLabel());
```
### M15: Teach studio in live browser mode: show the webcam (mirrored) after the stage switches to service mode

Offset 4766417.

Old:
```js
  function useSim() { stopCamera(); stage.src = "sim"; stage.root.classList.remove("mirror"); stage.video.removeAttribute("src"); stage.video.load(); stageStatus(); }
```
New:
```js
  function useSim() { stopCamera(); stage.src = "sim"; stage.root.classList.remove("mirror"); stage.video.removeAttribute("src"); stage.video.load(); attachStageCam(); stageStatus(); }
```
### M16: Teach studio stage label in live browser mode

Offset 4766687.

Old:
```js
t = socket.isMock() ? "Glasses simulation" : "Live from the app's camera"; cls = "ok"; }
```
New:
```js
t = socket.isMock() ? "Glasses simulation" : liveBrowser() ? (cam.stream ? "Live from your camera" : "Camera not available") : "Live from the app's camera"; cls = liveBrowser() && !cam.stream ? "bad" : "ok"; }
```
### M17: Teach studio: the service's landmarks are drawn over the webcam with the image mapping (live browser mode)

Offset 4767827.

Old:
```js
    if (!holo || !holo.hands) return [];
```
New:
```js
    if (!holo || !holo.hands) return [];
    if (liveBrowser() && stage.video.videoWidth) { var vw = stage.video.videoWidth, vh = stage.video.videoHeight; return holo.hands.map(function (h) { return { pts: h.points.map(function (p) { return camPoint(p, vw, vh); }), sim: true }; }); }
```
### M18: Teach studio: the stage keeps the webcam's aspect ratio (live browser mode)

Offset 4768979.

Old:
```js
    if (stage.src === "sim") { vw = 4; vh = 3; }
```
New:
```js
    if (stage.src === "sim" && !(liveBrowser() && v.videoWidth)) { vw = 4; vh = 3; }
```
### M19: Teach studio: no drawn head outline over the real webcam

Offset 4770194.

Old:
```js
    if (stage.src === "sim") {
      // the wearer
```
New:
```js
    if (stage.src === "sim" && !(liveBrowser() && stage.video.videoWidth)) {
      // the wearer
```
### M20: Take guidance off the mock: after the 3-2-1 countdown the stage badge reads 'Sign now… hands down to finish'

Offset 4776557.

Old:
```js
rec.purpose = purpose; teach.sub = "recording"; stage.rec.hidden = false;
```
New:
```js
rec.purpose = purpose; teach.sub = "recording"; stage.rec.textContent = socket.isMock() ? "Recording" : "Sign now… hands down to finish"; stage.rec.hidden = false;
```
### M21: Take guidance off the mock in the dialog text

Offset 4787442.

Old:
```js
p(busy ? (teach.sub === "countdown" ? "Get ready…" : "Recording. Sign it at a normal pace.")
```
New:
```js
p(busy ? (teach.sub === "countdown" ? "Get ready…" : socket.isMock() ? "Recording. Sign it at a normal pace." : "Sign now… hands down to finish")
```

### M verification

- `html.parser` parses the file; all 6 inline scripts pass `node --check`.
- Headless Chrome 156 (`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`) against the local service (`CONFIDENCE_THRESHOLD=0`):
  - **Live, `/`**: the Start card shows (name, NSL/ASL/BSL, Read my signs aloud checked). Start -> `POST /rooms`, `/ws?room=ZVXW&role=signer&name=Amaka`,
    the address bar becomes `/?room=ZVXW`, `GET /rooms/ZVXW` lists Amaka as signer, the server logs `ui_ready view=phone`, `settings language=ase`,
    `session live` and `frames received: 1 / 100 / 200 (640x480)`. Room line `Live · 0 participants · Room ZVXW`, room card with
    `localhost:8000/join/ZVXW` and Copy link. `tests/replay.py --participant Bob --room ZVXW --speech "hello can you help me"` -> caption "Bob: hello can you help me".
    Pause -> `Paused · ...`, resume -> `Live · ...`. Typed text -> `speech_text` -> caption "Phone mic: ...". No intro and no tour.
  - **Live with a real signing video as the fake camera** (`--use-file-for-fake-video-capture`, the wave clip): the Your hands panel shows the mirrored
    video with the skeleton on the hand; the service recognises WAVE and the `sentence` is spoken with `speechSynthesis` (read aloud on).
    Add a sign "wavetest": 3-2-1, "Sign now… hands down to finish", `teach_start` -> `teach_progress` -> "Take 1 of 2 recorded", then
    "Take 2 of 2 recorded" / "WAVETEST is recorded" with Save. Cancelled (not saved) so the library under tools/ is untouched.
  - **Reconnect**: stopping the service shows `Reconnecting… · Room SWCU`; after restarting it the page rejoins SWCU as the signer and frames resume.
  - **Camera denied** (getUserMedia rejected with NotAllowedError): one-line note "Camera blocked. Allow it in the browser to sign." in the
    panel and a toast; the room is still created and joined.
  - **`?mock=1`**: the old intro opens on first run, typed text gives the mock caption, D opens the demo drawer, Play demo runs; no fetch, no getUserMedia.
  - **Bridge** (fake `window.insync` before the scripts): sends `ui_ready view=phone` and `settings`; no `POST /rooms`, no getUserMedia, no frames;
    old intro on first run; `room` -> "Room ABCD · 1 participant"; captions "Bob" / "You"; mic -> `insync.listen`, `speechResult` -> `speech_text`;
    pause -> `session paused` + `insync.setSession('paused')`.
