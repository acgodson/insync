import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'calibration_screen.dart';
import 'calibration_service.dart';
import 'face_mesh_painter.dart';
import 'stream_screen.dart';

// Calibration result: mesh on a still, stability verdict, remember + save / redo
class ResultsScreen extends StatefulWidget {
  const ResultsScreen({
    super.key,
    required this.profile,
    required this.still,
    required this.stillWidth,
    required this.stillHeight,
    required this.landmarks,
    required this.edges,
  });

  static const goodThreshold = 0.03; // TODO: tune further from observed stability scores

  final Map<String, dynamic> profile;
  final Uint8List still;
  final int stillWidth, stillHeight;
  final Float32List landmarks;
  final List<int> edges;

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  bool _remember = true;

  @override
  Widget build(BuildContext context) {
    final stability = widget.profile['stability'] as Map<String, dynamic>;
    final good = widget.profile['quality'] == 'good';
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(title: const Text('Calibration result')),
      body: Column(
        children: [
          Expanded(
            child: Center(
              child: Transform.flip(
                flipX: true,
                child: AspectRatio(
                  aspectRatio: widget.stillWidth / widget.stillHeight,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.memory(widget.still, fit: BoxFit.fill),
                      CustomPaint(painter: FaceMeshPainter(widget.landmarks, widget.edges)),
                    ],
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                Text(
                  good ? 'Good' : 'Retry',
                  style: TextStyle(
                      color: good ? Colors.greenAccent : Colors.amber, fontSize: 24, fontWeight: FontWeight.bold),
                ),
                Text(
                  'stability ${(stability['overall'] as double).toStringAsFixed(4)} '
                  '(straight ${(stability['straight'] as double).toStringAsFixed(4)}, '
                  'left ${(stability['left'] as double).toStringAsFixed(4)}, '
                  'right ${(stability['right'] as double).toStringAsFixed(4)})',
                  style: const TextStyle(color: Colors.white54, fontSize: 11),
                ),
                Text(
                  'head width ${(widget.profile['headWidthMm'] as double).toStringAsFixed(0)} mm (est.), '
                  'IPD ${(widget.profile['ipd'] as double).toStringAsFixed(3)}',
                  style: const TextStyle(color: Colors.white54, fontSize: 11),
                ),
                CheckboxListTile(
                  value: _remember,
                  onChanged: (v) => setState(() => _remember = v ?? true),
                  title: const Text('Remember this profile', style: TextStyle(color: Colors.white)),
                  controlAffinity: ListTileControlAffinity.leading,
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    OutlinedButton(
                      onPressed: () => Navigator.of(context)
                          .pushReplacement(MaterialPageRoute(builder: (_) => const CalibrationScreen())),
                      child: const Text('Redo'),
                    ),
                    const SizedBox(width: 16),
                    FilledButton(
                      onPressed: () async {
                        await CalibrationService().save(widget.profile, remember: _remember);
                        if (!context.mounted) return;
                        Navigator.of(context)
                            .pushReplacement(MaterialPageRoute(builder: (_) => const StreamScreen()));
                      },
                      child: const Text('Save'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
