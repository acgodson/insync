import 'dart:async';
import 'dart:convert';
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

// Home: the web UI in a WebView, bridged to native speech, the camera stream and the service
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
  speak: function (t) { insyncNative.postMessage(JSON.stringify({call: 'speak', text: String(t)})); },
  listen: function () { insyncNative.postMessage(JSON.stringify({call: 'listen'})); },
  stopListening: function () { insyncNative.postMessage(JSON.stringify({call: 'stopListening'})); },
  setSession: function (s) { insyncNative.postMessage(JSON.stringify({call: 'setSession', state: String(s)})); },
  send: function (j) { insyncNative.postMessage(JSON.stringify({call: 'send', json: typeof j === 'string' ? j : JSON.stringify(j)})); },
});
window.dispatchEvent(new Event('insync-ready'));
''';

  AppSettings? _settings;
  WebViewController? _web;
  ServiceClient? _service;
  StreamSubscription? _frameSub;
  final _tts = FlutterTts();
  final _stt = SpeechToText();
  bool _live = true;
  bool _connected = false;
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
        onPageStarted: (_) => _web?.runJavaScript(_bridgeJs),
        onPageFinished: (_) async {
          await _web?.runJavaScript(_bridgeJs);
          _sendVoices();
        },
      ));
    final android = web.platform;
    if (android is AndroidWebViewController) {
      android.setMediaPlaybackRequiresUserGesture(false);
      android.setOnPlatformPermissionRequest((req) => req.grant()); // page camera/mic
    }
    _web = web;
    _loadUi();

    _service = ServiceClient(s.serviceUrl, onMessage: _fromService, onState: (c) {
      setState(() => _connected = c);
      if (c) {
        _service!.send({'type': 'ui_ready', 'view': 'phone'});
        _service!.send({'type': 'session', 'state': _live ? 'live' : 'paused'});
      }
    });
    _service!.connect();

    _frameSub = _frames.receiveBroadcastStream().listen(_onNative);
    _control.invokeMethod('start', {'fallback': true});
    _fpsTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (mounted) setState(() { _fps = _sentInWindow / 2; _sentInWindow = 0; });
    });
    setState(() {});
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

  // Native stream -> service (throttled to 10 fps)
  void _onNative(dynamic event) {
    if (event is Uint8List) {
      if (_sentInWindow == 0 && _lastSent == 0) print('frames: first native frame (${event.length} bytes)');
      final now = DateTime.now().millisecondsSinceEpoch;
      if (!_live || now - _lastSent < 1000 ~/ _sendFps) return;
      _lastSent = now;
      _sentInWindow++;
      // TODO(phase2): carry the real frame size from native; MEDIUM glasses frames are 504x896
      _service?.send({'type': 'frame', 'jpeg': base64Encode(event), 'w': 504, 'h': 896});
    } else if (event is String) {
      print('native: $event');
      setState(() => _nativeStatus = event);
    }
  }

  // Service -> page
  void _fromService(String json) {
    try {
      _lastType = (jsonDecode(json) as Map)['type']?.toString() ?? '';
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
        _service?.sendRaw(m['json'] as String);
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
    final list = [for (final v in (voices as List? ?? [])) {'name': v['name'], 'locale': v['locale']}];
    _toPage('voices', list);
  }

  void _toPage(String fn, Object arg) {
    _web?.runJavaScript('window.insync && window.insync.$fn && window.insync.$fn(${jsonEncode(arg)})');
  }

  void _setSession(bool live) {
    _live = live;
    _service?.send({'type': 'session', 'state': live ? 'live' : 'paused'});
    _control.invokeMethod(live ? 'start' : 'stop', live ? {'fallback': true} : null);
  }

  Future<void> _openSettings() async {
    final changed = await Navigator.of(context).push<bool>(
        MaterialPageRoute(builder: (_) => SettingsScreen(settings: _settings!)));
    if (changed == true && mounted) {
      _service?.close();
      _service = ServiceClient(_settings!.serviceUrl, onMessage: _fromService, onState: (c) {
        setState(() => _connected = c);
        if (c) _service!.send({'type': 'ui_ready', 'view': 'phone'});
      });
      _service!.connect();
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
              child: Container(
                height: 28,
                color: const Color(0xFF141415),
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Row(
                  children: [
                    const Text('InSync', style: TextStyle(color: Colors.white70, fontSize: 12)),
                    const Spacer(),
                    Icon(Icons.circle, size: 8, color: _connected ? Colors.greenAccent : Colors.redAccent),
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
              child: _web == null
                  ? const Center(child: CircularProgressIndicator())
                  : WebViewWidget(controller: _web!),
            ),
          ],
        ),
      ),
    );
  }
}
