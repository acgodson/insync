import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

import 'calibration_screen.dart';
import 'calibration_service.dart';

// Startup routing: saved profile + remember on -> streaming, otherwise calibration
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  final service = CalibrationService();
  final calibrated = await service.remember() && await service.load() != null;
  runApp(MaterialApp(
    title: 'Almero',
    theme: ThemeData.dark(useMaterial3: true),
    home: calibrated ? const StreamScreen() : const CalibrationScreen(),
  ));
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
  int _countdown = 0; // seconds left while recording, 0 when idle
  Timer? _countdownTimer;

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
      } else if (event is Map && event.containsKey('recording')) {
        _countdownTimer?.cancel();
        setState(() => _countdown = 0);
        _showRecorded(event['path'] as String, event['frames'] as int);
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

  @override
  void dispose() {
    _countdownTimer?.cancel();
    super.dispose();
  }

  // Record mode: optional label -> 10 s of raw frames saved natively
  Future<void> _record() async {
    final controller = TextEditingController();
    final label = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Record 10 seconds'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Label (optional)', hintText: 'e.g. hello'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, controller.text), child: const Text('Record')),
        ],
      ),
    );
    if (label == null || !mounted) return;
    try {
      await _control.invokeMethod('record', {'label': label});
    } on PlatformException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message ?? e.code)));
      return;
    }
    setState(() => _countdown = 10);
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return;
      setState(() => _countdown = (_countdown - 1).clamp(0, 10));
      if (_countdown == 0) t.cancel();
    });
  }

  void _showRecorded(String path, int frames) {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Recorded $frames frames', style: Theme.of(ctx).textTheme.titleMedium),
            const SizedBox(height: 8),
            SelectableText(path, style: const TextStyle(fontSize: 12, color: Colors.white70)),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close')),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: () { Navigator.pop(ctx); _record(); },
                  child: const Text('Record again'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // Export: zip all recordings for adb pull
  Future<void> _export() async {
    final zip = await _control.invokeMethod<String>('export');
    if (!mounted || zip == null) return;
    final name = zip.split('/').last;
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Exported'),
        content: SelectableText(
          '$zip\n\nadb pull /sdcard/Android/data/com.almero.app/files/$name .',
          style: const TextStyle(fontSize: 12),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('OK'))],
      ),
    );
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
      appBar: AppBar(
        title: const Text('Almero'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => const CalibrationScreen())),
            child: const Text('Recalibrate'),
          ),
        ],
      ),
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
            if (_countdown > 0)
              Center(
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                  decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(12)),
                  child: Text('REC $_countdown',
                      style: const TextStyle(color: Colors.redAccent, fontSize: 36, fontWeight: FontWeight.bold)),
                ),
              ),
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
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      OutlinedButton.icon(
                          onPressed: _frame == null || _countdown > 0 ? null : _record,
                          icon: const Icon(Icons.fiber_manual_record, color: Colors.redAccent, size: 16),
                          label: const Text('Record')),
                      const SizedBox(width: 16),
                      OutlinedButton(onPressed: _export, child: const Text('Export')),
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
