import 'dart:async';
import 'dart:convert';
import 'dart:io';

// WebSocket client for the InSync service: one connection, reconnects every 2 s while dropped
class ServiceClient {
  ServiceClient(this.url, {required this.onMessage, required this.onState});

  final String url;
  final void Function(String json) onMessage;
  final void Function(bool connected) onState;

  WebSocket? _socket;
  bool _closed = false;
  bool _connecting = false;
  Timer? _retry;
  bool get connected => _socket != null;

  Future<void> connect() async {
    if (_closed || _connecting || _socket != null) return;
    _connecting = true;
    try {
      final s = await WebSocket.connect(url).timeout(const Duration(seconds: 5));
      _socket = s;
      print('service: connected $url');
      onState(true);
      s.listen((data) => onMessage(data is String ? data : utf8.decode(data as List<int>)),
          onDone: _dropped, onError: (_) => _dropped(), cancelOnError: true);
    } catch (e) {
      print('service: connect failed ($e), retrying');
      _scheduleRetry();
    } finally {
      _connecting = false;
    }
  }

  void _dropped() {
    if (_socket == null) return;
    _socket = null;
    print('service: disconnected');
    onState(false);
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (_closed) return;
    _retry?.cancel();
    _retry = Timer(const Duration(seconds: 2), connect);
  }

  void send(Map<String, dynamic> message) {
    message.putIfAbsent('ts', () => DateTime.now().millisecondsSinceEpoch);
    _socket?.add(jsonEncode(message));
  }

  void sendRaw(String json) => _socket?.add(json);

  void close() {
    _closed = true;
    _retry?.cancel();
    _socket?.close();
    _socket = null;
  }
}
