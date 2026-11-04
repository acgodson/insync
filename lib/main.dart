import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  runApp(const MaterialApp(title: 'Almero', home: StreamScreen()));
}

class StreamScreen extends StatefulWidget {
  const StreamScreen({super.key});
  @override
  State<StreamScreen> createState() => _StreamScreenState();
}

class _StreamScreenState extends State<StreamScreen> {
  static const _control = MethodChannel('almero/control');
  static const _frames = EventChannel('almero/frames');

  Uint8List? _frame;
  String _status = 'Idle';
  Map? _device;

  @override
  void initState() {
    super.initState();
    _frames.receiveBroadcastStream().listen((event) {
      if (!mounted) return;
      if (event is String) {
        setState(() {
          _status = event;
          if (event == 'Session: STOPPED') _frame = null;
        });
      } else if (event is Uint8List) {
        setState(() => _frame = event);
      } else if (event is Map && event.containsKey('device')) {
        setState(() => _device = event['device'] == null ? null : event);
      } else if (event is Map) {
        final received = DateTime.now().millisecondsSinceEpoch;
        setState(() => _frame = event['jpeg'] as Uint8List);
        SchedulerBinding.instance.addPostFrameCallback((_) {
          _control.invokeMethod('frameDrawn', {
            'n': event['n'],
            'received': received,
            'drawn': DateTime.now().millisecondsSinceEpoch,
          });
        });
      }
    });
  }

  // Glasses status pill
  Widget _devicePill(Map d) {
    final battery = d['battery'] as int;
    final charging = d['charging'] == 'CHARGING';
    final worn = d['worn'] == 'DONNED';
    final thermal = d['thermal'] as String;
    final hot = !{'UNKNOWN', 'NONE', 'LIGHT'}.contains(thermal);
    Color color = Colors.white;
    if (battery > 0 && battery <= 10) {
      color = Colors.redAccent;
    } else if (battery > 0 && battery <= 20) {
      color = Colors.amber;
    }
    final parts = <String>[
      battery == 0 ? 'Battery --' : 'Battery $battery%',
      if (charging) 'charging',
      if (!worn) 'not worn',
      if (hot) 'hot: ${thermal.toLowerCase()}',
    ];
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(16)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(charging ? Icons.battery_charging_full : Icons.battery_std, size: 16, color: color),
          const SizedBox(width: 6),
          Text(parts.join(' · '), style: TextStyle(color: color, fontSize: 12)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            Center(
              child: _frame == null
                  ? const Text('No frames yet', style: TextStyle(color: Colors.white54))
                  : Image.memory(_frame!, gaplessPlayback: true, fit: BoxFit.contain),
            ),
            if (_device != null)
              Positioned(top: 8, right: 8, child: _devicePill(_device!)),
            Positioned(
              left: 0,
              right: 0,
              bottom: 8,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(_status, style: const TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      FilledButton(
                          onPressed: () => _control.invokeMethod('start'), child: const Text('Start')),
                      const SizedBox(width: 16),
                      OutlinedButton(
                          onPressed: () {
                            setState(() => _frame = null);
                            _control.invokeMethod('stop');
                          },
                          child: const Text('Stop')),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
