import 'package:flutter/material.dart';

import 'app_settings.dart';
import 'calibration_screen.dart';
import 'stream_screen.dart';

// Hidden settings (long-press the top bar): web UI source, service host, debug strip, tools
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.settings});
  final AppSettings settings;
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final _dev = TextEditingController(text: widget.settings.devUrl);
  late final _prod = TextEditingController(text: widget.settings.prodUrl);
  late final _host = TextEditingController(text: widget.settings.serviceHost);

  Future<void> _save() async {
    final s = widget.settings;
    s.devUrl = _dev.text.trim();
    s.prodUrl = _prod.text.trim();
    s.serviceHost = _host.text.trim();
    await s.save();
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.settings;
    return Scaffold(
      appBar: AppBar(title: const Text('InSync settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Web UI source'),
          SegmentedButton<WebUiSource>(
            segments: const [
              ButtonSegment(value: WebUiSource.dev, label: Text('dev')),
              ButtonSegment(value: WebUiSource.asset, label: Text('asset')),
              ButtonSegment(value: WebUiSource.prod, label: Text('prod')),
            ],
            selected: {s.source},
            onSelectionChanged: (v) => setState(() => s.source = v.first),
          ),
          TextField(controller: _dev, decoration: const InputDecoration(labelText: 'dev URL (Vite)')),
          TextField(controller: _prod, decoration: const InputDecoration(labelText: 'prod URL')),
          TextField(controller: _host, decoration: const InputDecoration(labelText: 'service host (ip:port)')),
          SwitchListTile(
            title: const Text('Debug strip'),
            value: s.debugStrip,
            onChanged: (v) => setState(() => s.debugStrip = v),
          ),
          const SizedBox(height: 16),
          FilledButton(onPressed: _save, child: const Text('Save and reload')),
          const Divider(height: 32),
          OutlinedButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const CalibrationScreen())),
            child: const Text('Face calibration'),
          ),
          const SizedBox(height: 8),
          OutlinedButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const StreamScreen())),
            child: const Text('Glasses stream / Record'),
          ),
        ],
      ),
    );
  }
}
