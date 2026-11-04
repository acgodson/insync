import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'app_settings.dart';
import 'service_client.dart';
import 'settings_screen.dart';

// Home: instant room + the signer web UI in a WebView, bridged to native speech, camera and the service
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  static const _control = MethodChannel('insync/control');
  static const _frames = EventChannel('insync/frames');
  static const _sendFps = 10;

  // Page-side API (window.insync): speak, listen, stopListening, setSession, send;
  // the page assigns onMessage(json), speechResult(text), voices(list).
  static const _bridgeJs = '''
window.insync = window.insync || {};
Object.assign(window.insync, {
  native: true,
  serviceBase: 'SERVICE_BASE',
  speak: function (t) { insyncNative.postMessage(JSON.stringify({call: 'speak', text: String(t)})); },
  listen: function () { insyncNative.postMessage(JSON.stringify({call: 'listen'})); },
  stopListening: function () { insyncNative.postMessage(JSON.stringify({call: 'stopListening'})); },
  setSession: function (s) { insyncNative.postMessage(JSON.stringify({call: 'setSession', state: String(s)})); },
  send: function (j) { insyncNative.postMessage(JSON.stringify({call: 'send', json: typeof j === 'string' ? j : JSON.stringify(j)})); },
});
window.dispatchEvent(new Event('insync-ready'));
''';

  String get _bridge => _bridgeJs.replaceFirst('SERVICE_BASE', _settings?.baseUrl ?? '');

  AppSettings? _settings;
  WebViewController? _web;
  ServiceClient? _service;
  StreamSubscription? _frameSub;
  final _tts = FlutterTts();
  final _stt = SpeechToText();
  final _voices = <String, Map<String, String>>{}; // name -> {name, locale}
  bool _live = true;
  bool _connected = false;
  String _roomCode = '';
  String _roomLink = '';
  int _participants = 0;
  Uint8List? _preview;
  bool _previewLarge = false;
  bool _mirror = false;
  int _lastSent = 0;
  int _sentInWindow = 0;
  double _fps = 0;
  String _lastType = '';
  String _nativeStatus = '';
  Timer? _fpsTimer;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final s = await AppSettings.load();
    _settings = s;
    final web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF0F0F10))
      ..setUserAgent('InSyncApp')
      ..addJavaScriptChannel('insyncNative', onMessageReceived: (m) => _fromPage(m.message))
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (_) => _web?.runJavaScript(_bridge),
        onPageFinished: (_) async {
          await _web?.runJavaScript(_bridge);
          _sendVoices();
        },
        onWebResourceError: (e) {
          // Hosted UI unreachable: fall back to the bundled copy
          if (e.isForMainFrame == true && _settings?.source != WebUiSource.asset) {
            print('web: ${e.description}, falling back to the bundled UI');
            _web?.loadFlutterAsset('assets/web/index.html');
          }
        },
      ));
    final android = web.platform;
    if (android is AndroidWebViewController) {
      android.setMediaPlaybackRequiresUserGesture(false);
      android.setOnPlatformPermissionRequest((req) => req.grant()); // page camera/mic
    }
    _web = web;
    _loadUi();
    await _openRoom();
    _frameSub = _frames.receiveBroadcastStream().listen(_onNative);
    _control.invokeMethod('start', {'fallback': true});
    _fpsTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (mounted) setState(() { _fps = _sentInWindow / 2; _sentInWindow = 0; });
    });
    if (mounted) setState(() {});
  }

  // Instant room: ask the service for a code, fall back to a local one (the service creates it on join)
  Future<void> _openRoom() async {
    final s = _settings!;
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final req = await client.postUrl(Uri.parse('${s.baseUrl}/rooms'));
      final res = await req.close();
      final body = jsonDecode(await res.transform(utf8.decoder).join()) as Map;
      _roomCode = body['code'] as String;
      _roomLink = body['link'] as String;
      client.close();
    } catch (e) {
      print('room: create failed ($e), using a local code');
      _roomCode = String.fromCharCodes(List.generate(4, (i) => 65 + (DateTime.now().microsecond + i * 7) % 26));
      _roomLink = '${s.baseUrl}/join/$_roomCode';
    }
    _service?.close();
    _service = ServiceClient('${s.wsBase}/ws?room=$_roomCode&role=signer&name=Signer',
        onMessage: _fromService, onState: (c) {
      if (!mounted) return;
      setState(() => _connected = c);
      if (c) {
        _service!.send({'type': 'ui_ready', 'view': 'phone'});
        _service!.send({'type': 'session', 'state': _live ? 'live' : 'paused'});
      }
    });
    _service!.connect();
  }

  void _loadUi() {
    final s = _settings!;
    switch (s.source) {
      case WebUiSource.dev:
        _web!.loadRequest(Uri.parse(s.devUrl));
      case WebUiSource.prod:
        _web!.loadRequest(Uri.parse(s.prodUrl.isEmpty ? s.devUrl : s.prodUrl));
      case WebUiSource.asset:
        _web!.loadFlutterAsset('assets/web/index.html');
    }
  }

  // Native stream -> service (throttled to 10 fps) + preview
  void _onNative(dynamic event) {
    if (event is Uint8List) {
      final now = DateTime.now().millisecondsSinceEpoch;
      if (now - _lastSent < 1000 ~/ _sendFps) return;
      _lastSent = now;
      _sentInWindow++;
      final size = _jpegSize(event);
      if (_live) {
        _service?.send({'type': 'frame', 'jpeg': base64Encode(event), 'w': size[0], 'h': size[1]});
      }
      setState(() => _preview = event);
    } else if (event is String) {
      print('native: $event');
      setState(() {
        _nativeStatus = event;
        if (event.startsWith('Source: mock')) _mirror = true;
        if (event.startsWith('Source: glasses')) _mirror = false;
      });
    }
  }

  // Width and height from the JPEG start-of-frame marker
  static List<int> _jpegSize(Uint8List d) {
    var i = 2;
    while (i + 9 < d.length) {
      if (d[i] != 0xFF) { i++; continue; }
      final marker = d[i + 1];
      if (marker >= 0xC0 && marker <= 0xCF && marker != 0xC4 && marker != 0xC8 && marker != 0xCC) {
        return [(d[i + 7] << 8) | d[i + 8], (d[i + 5] << 8) | d[i + 6]];
      }
      i += 2 + ((d[i + 2] << 8) | d[i + 3]);
    }
    return [0, 0];
  }

  // Service -> page
  void _fromService(String json) {
    try {
      final m = jsonDecode(json) as Map;
      _lastType = m['type']?.toString() ?? '';
      if (_lastType == 'room') {
        _roomCode = m['code']?.toString() ?? _roomCode;
        _participants = ((m['participants'] as List?)?.where((p) => p['role'] == 'participant').length) ?? 0;
      }
    } catch (_) {}
    _web?.runJavaScript('window.insync && window.insync.onMessage && window.insync.onMessage(${jsonEncode(json)})');
    if (mounted) setState(() {});
  }

  // Page -> native
  Future<void> _fromPage(String raw) async {
    final m = jsonDecode(raw) as Map;
    switch (m['call']) {
      case 'speak':
        await _tts.speak(m['text'] as String);
      case 'listen':
        await _listen();
      case 'stopListening':
        await _stt.stop();
      case 'setSession':
        _setSession(m['state'] == 'live');
      case 'send':
        final json = m['json'] as String;
        _service?.sendRaw(json);
        _applyPageSettings(json);
    }
  }

  Future<void> _listen() async {
    if (!_stt.isAvailable && !await _stt.initialize()) return;
    await _stt.listen(onResult: (r) {
      if (r.finalResult) _toPage('speechResult', r.recognizedWords);
    });
  }

  Future<void> _sendVoices() async {
    final voices = await _tts.getVoices;
    final list = [for (final v in (voices as List? ?? [])) {'name': '${v['name']}', 'locale': '${v['locale']}'}];
    for (final v in list) {
      _voices[v['name']!] = v;
    }
    _toPage('voices', list);
  }

  // settings {voice} from the page selects the native TTS voice
  void _applyPageSettings(String json) {
    try {
      final m = jsonDecode(json) as Map;
      if (m['type'] != 'settings') return;
      final voice = _voices[m['voice']?.toString()];
      if (voice != null) _tts.setVoice(voice);
    } catch (_) {}
  }

  void _toPage(String fn, Object arg) {
    _web?.runJavaScript('window.insync && window.insync.$fn && window.insync.$fn(${jsonEncode(arg)})');
  }

  void _setSession(bool live) {
    _live = live;
    _service?.send({'type': 'session', 'state': live ? 'live' : 'paused'});
    _control.invokeMethod(live ? 'start' : 'stop', live ? {'fallback': true} : null);
    setState(() {});
  }

  // Plain-words camera state for the status line
  String get _stateText {
    final s = _nativeStatus;
    if (!_live) return 'Paused';
    if (s.startsWith('Source:') || s.startsWith('Stream:') || s.startsWith('Session:')) {
      return _mirror ? 'Phone camera' : 'Glasses: connected';
    }
    if (s.startsWith('Waiting for glasses')) return 'Waiting for glasses (wear them)';
    if (s.startsWith('No glasses')) return 'No glasses: phone camera';
    if (s.startsWith('Registering')) return 'Approve InSync in the Meta AI app';
    if (s.startsWith('No eligible')) return 'Glasses not found';
    return s.isEmpty ? 'Starting camera' : s;
  }

  // Tap the status line to switch between the glasses and the phone camera
  void _pickSource() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.visibility),
            title: const Text('Use glasses'),
            subtitle: const Text('Wear them and keep Meta AI connected'),
            onTap: () { Navigator.pop(ctx); setState(() => _nativeStatus = 'Waiting for glasses'); _control.invokeMethod('source', {'to': 'glasses'}); },
          ),
          ListTile(
            leading: const Icon(Icons.phone_android),
            title: const Text('Use phone camera'),
            onTap: () { Navigator.pop(ctx); _control.invokeMethod('source', {'to': 'phone'}); },
          ),
        ]),
      ),
    );
  }

  void _shareRoom() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Room $_roomCode'),
        content: SelectableText(_roomLink.isEmpty ? 'No link yet' : _roomLink),
        actions: [
          TextButton(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: _roomLink));
              Navigator.pop(ctx);
            },
            child: const Text('Copy link'),
          ),
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
        ],
      ),
    );
  }

  Future<void> _openSettings() async {
    final changed = await Navigator.of(context).push<bool>(
        MaterialPageRoute(builder: (_) => SettingsScreen(settings: _settings!)));
    if (changed == true && mounted) {
      await _openRoom();
      _loadUi();
      setState(() {});
    }
  }

  @override
  void dispose() {
    _frameSub?.cancel();
    _fpsTimer?.cancel();
    _service?.close();
    _control.invokeMethod('stop');
    super.dispose();
  }

  Widget _previewWidget() {
    final img = _preview;
    if (img == null) return const SizedBox.shrink();
    final w = _previewLarge ? 220.0 : 90.0;
    return GestureDetector(
      onTap: () => setState(() => _previewLarge = !_previewLarge),
      child: Container(
        width: w,
        height: w * 4 / 3,
        decoration: BoxDecoration(
          border: Border.all(color: Colors.white24),
          borderRadius: BorderRadius.circular(8),
        ),
        clipBehavior: Clip.antiAlias,
        child: Transform.flip(
          flipX: _mirror,
          child: Image.memory(img, gaplessPlayback: true, fit: BoxFit.cover),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _settings;
    return Scaffold(
      backgroundColor: const Color(0xFF0F0F10),
      body: SafeArea(
        child: Column(
          children: [
            GestureDetector(
              onLongPress: _openSettings,
              onTap: _shareRoom,
              child: Container(
                height: 32,
                color: const Color(0xFF141415),
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Row(
                  children: [
                    const Text('InSync', style: TextStyle(color: Colors.white70, fontSize: 12)),
                    const SizedBox(width: 10),
                    Text(_roomCode.isEmpty ? '' : 'Room $_roomCode',
                        style: const TextStyle(color: Color(0xFFF0B54A), fontSize: 12, fontWeight: FontWeight.w600)),
                    if (_participants > 0)
                      Text('  · $_participants in', style: const TextStyle(color: Colors.white54, fontSize: 12)),
                    const Spacer(),
                    GestureDetector(
                      onTap: _pickSource,
                      child: Text(_stateText, style: const TextStyle(color: Colors.white54, fontSize: 11, decoration: TextDecoration.underline)),
                    ),
                    const SizedBox(width: 8),
                    Icon(Icons.circle, size: 8, color: _connected ? Colors.greenAccent : Colors.redAccent),
                    const SizedBox(width: 6),
                    const Icon(Icons.share, size: 14, color: Colors.white54),
                  ],
                ),
              ),
            ),
            if (s != null && s.debugStrip)
              Container(
                width: double.infinity,
                color: Colors.black,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
                child: Text(
                  'service ${_connected ? "connected" : "offline"} · ${_fps.toStringAsFixed(1)} fps sent · last ${_lastType.isEmpty ? "-" : _lastType} · $_nativeStatus',
                  style: const TextStyle(color: Colors.white54, fontSize: 10),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            Expanded(
              child: Stack(
                children: [
                  _web == null
                      ? const Center(child: CircularProgressIndicator())
                      : WebViewWidget(controller: _web!),
                  Positioned(top: 8, right: 8, child: _previewWidget()),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
