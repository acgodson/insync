import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'face_mesh_painter.dart';
import 'results_screen.dart';

// Guided 3-step head calibration using the phone's front camera
class CalibrationScreen extends StatefulWidget {
  const CalibrationScreen({super.key});
  @override
  State<CalibrationScreen> createState() => _CalibrationScreenState();
}

enum _Step { straight, left, right }

class _Capture {
  _Capture(this.landmarks, this.matrix, this.stability, this.still, this.w, this.h);
  final Float32List landmarks;
  final List<double>? matrix;
  final double stability;
  final Uint8List still;
  final int w, h;
}

class _CalibrationScreenState extends State<CalibrationScreen> {
  static const _control = MethodChannel('insync/calibration');
  static const _frames = EventChannel('insync/calibration_frames');

  // Capture tuning
  static const _holdMs = 1000;
  static const _minBrightness = 60;
  static const _minFaceWidth = 0.30; // normalised, fraction of image width
  static const _maxFaceWidth = 0.65;
  static const _straightYaw = 8.0;
  static const _turnMin = 12.0, _turnMax = 45.0;
  static const _logMetrics = false; // per-frame metrics to logcat (tag "flutter")
  static const _noseTip = 1, _leftCheek = 234, _rightCheek = 454;

  List<int> _edges = const [];
  Uint8List? _jpeg;
  int _w = 1, _h = 1;
  Float32List? _landmarks;
  String _hint = 'Starting camera...';
  double _yaw = 0;
  _Step _step = _Step.straight;
  final Map<_Step, _Capture> _captures = {};

  // Hold window
  int? _holdStart;
  final List<Float32List> _held = [];
  final List<List<double>> _heldMatrices = [];
  double _progress = 0;

  @override
  void initState() {
    super.initState();
    _control.invokeMethod<List<dynamic>>('edges').then((e) => setState(() => _edges = e!.cast<int>()));
    _frames.receiveBroadcastStream().listen(_onFrame);
    _control.invokeMethod('start');
  }

  @override
  void dispose() {
    _control.invokeMethod('stop');
    super.dispose();
  }

  void _onFrame(dynamic event) {
    if (!mounted || event is! Map) return;
    if (event['error'] != null) {
      setState(() => _hint = event['error'] as String);
      return;
    }
    final jpeg = event['jpeg'] as Uint8List;
    final w = event['w'] as int, h = event['h'] as int;
    final ts = event['ts'] as int;
    final brightness = event['brightness'] as int;
    final lm = event['landmarks'] as Float32List?;
    final matrix = (event['matrix'] as Float32List?)?.toList();

    String hint;
    bool ok = false;
    double yaw = 0;
    if (lm == null) {
      hint = 'Face not found. Look at the camera.';
    } else {
      yaw = _yawFromLandmarks(lm);
      final faceWidth = (lm[_rightCheek * 3] - lm[_leftCheek * 3]).abs();
      final cx = (lm[_rightCheek * 3] + lm[_leftCheek * 3]) / 2;
      final cy = (lm[_rightCheek * 3 + 1] + lm[_leftCheek * 3 + 1]) / 2;
      if (_logMetrics) {
        // ignore: avoid_print
        print('calib step=${_step.name} yawLm=${yaw.toStringAsFixed(1)} '
            'yawMx=${matrix != null ? _yawDeg(matrix).toStringAsFixed(1) : '-'} '
            'fw=${faceWidth.toStringAsFixed(2)} c=${cx.toStringAsFixed(2)},${cy.toStringAsFixed(2)} b=$brightness');
      }
      if (brightness < _minBrightness) {
        hint = 'Too dark. Find more light.';
      } else if (faceWidth < _minFaceWidth) {
        hint = 'Move closer.';
      } else if (faceWidth > _maxFaceWidth) {
        hint = 'Move back a little.';
      } else if (cx < 0.25 || cx > 0.75 || cy < 0.25 || cy > 0.75) {
        hint = 'Centre your face in the frame.';
      } else {
        switch (_step) {
          case _Step.straight:
            ok = yaw.abs() <= _straightYaw;
            hint = ok ? 'Hold still...' : 'Look straight at the camera.';
          case _Step.left:
            ok = yaw >= _turnMin && yaw <= _turnMax;
            hint = ok ? 'Hold still...' : (yaw < _turnMin ? 'Turn your head a bit more to the left.' : 'A little less.');
          case _Step.right:
            ok = -yaw >= _turnMin && -yaw <= _turnMax;
            hint = ok ? 'Hold still...' : (-yaw < _turnMin ? 'Turn your head a bit more to the right.' : 'A little less.');
        }
      }
    }

    if (ok && lm != null) {
      _holdStart ??= ts;
      _held.add(lm);
      if (matrix != null) _heldMatrices.add(matrix);
      _progress = ((ts - _holdStart!) / _holdMs).clamp(0, 1).toDouble();
      if (ts - _holdStart! >= _holdMs) _complete(jpeg, w, h);
    } else {
      _holdStart = null;
      _held.clear();
      _heldMatrices.clear();
      _progress = 0;
    }

    setState(() {
      _jpeg = jpeg;
      _w = w;
      _h = h;
      _landmarks = lm;
      _hint = hint;
      _yaw = yaw;
    });
  }

  // Yaw from the column-major facial transformation matrix (rotation about Y)
  double _yawDeg(List<double> m) => math.atan2(m[8], m[10]) * 180 / math.pi;

  // Yaw from the cheek-to-cheek line in the x/z plane (positive = subject's left cheek nearer)
  double _yawFromLandmarks(Float32List lm) {
    final dx = lm[_rightCheek * 3] - lm[_leftCheek * 3];
    final dz = lm[_rightCheek * 3 + 2] - lm[_leftCheek * 3 + 2];
    return math.atan2(dz, dx) * 180 / math.pi;
  }

  void _complete(Uint8List still, int w, int h) {
    final n = _held.length;
    final avg = Float32List(_held.first.length);
    for (final f in _held) {
      for (var i = 0; i < avg.length; i++) {
        avg[i] += f[i] / n;
      }
    }
    // Stability: RMS landmark jitter (x,y) over the last 60% of the hold, relative to face width
    final faceWidth = (avg[_rightCheek * 3] - avg[_leftCheek * 3]).abs();
    final window = _held.sublist((n * 0.4).floor());
    final ref = Float32List(avg.length);
    for (final f in window) {
      for (var i = 0; i < ref.length; i++) {
        ref[i] += f[i] / window.length;
      }
    }
    double varSum = 0;
    for (final f in window) {
      for (var i = 0; i < ref.length; i += 3) {
        final dx = f[i] - ref[i], dy = f[i + 1] - ref[i + 1];
        varSum += dx * dx + dy * dy;
      }
    }
    final stability = math.sqrt(varSum / (window.length * (ref.length ~/ 3))) / faceWidth;
    List<double>? matrix;
    if (_heldMatrices.isNotEmpty) {
      matrix = List<double>.filled(16, 0);
      for (final m in _heldMatrices) {
        for (var i = 0; i < 16; i++) {
          matrix[i] += m[i] / _heldMatrices.length;
        }
      }
    }
    _captures[_step] = _Capture(avg, matrix, stability, still, w, h);
    _holdStart = null;
    _held.clear();
    _heldMatrices.clear();
    _progress = 0;

    if (_step == _Step.straight) {
      _step = _Step.left;
    } else if (_step == _Step.left) {
      _step = _Step.right;
    } else {
      _finish();
    }
  }

  void _finish() {
    final s = _captures[_Step.straight]!, l = _captures[_Step.left]!, r = _captures[_Step.right]!;
    double dist(Float32List p, int a, int b) {
      final dx = p[a * 3] - p[b * 3], dy = p[a * 3 + 1] - p[b * 3 + 1], dz = p[a * 3 + 2] - p[b * 3 + 2];
      return math.sqrt(dx * dx + dy * dy + dz * dz);
    }

    final headWidth = dist(s.landmarks, _leftCheek, _rightCheek);
    final ipd = dist(s.landmarks, 468, 473); // iris centres
    const assumedIpdMm = 63.0; // TODO: replace with a measured IPD for metric scale
    final scale = ipd > 0 ? assumedIpdMm / ipd : 0.0;
    final overall = (s.stability + l.stability + r.stability) / 3;
    final profile = <String, dynamic>{
      'createdAt': DateTime.now().toIso8601String(),
      'landmarks': {
        'straight': s.landmarks.toList(),
        'left': l.landmarks.toList(),
        'right': r.landmarks.toList(),
      },
      'headWidth': headWidth,
      'ipd': ipd,
      'headWidthMm': headWidth * scale,
      'ipdMm': assumedIpdMm,
      'canonicalTransform': s.matrix,
      'stability': {'straight': s.stability, 'left': l.stability, 'right': r.stability, 'overall': overall},
      'quality': overall < ResultsScreen.goodThreshold ? 'good' : 'retry',
    };
    Navigator.of(context).pushReplacement(MaterialPageRoute(
      builder: (_) => ResultsScreen(
        profile: profile,
        still: s.still,
        stillWidth: s.w,
        stillHeight: s.h,
        landmarks: s.landmarks,
        edges: _edges,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final steps = _Step.values;
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(title: const Text('Calibration')),
      body: Column(
        children: [
          Expanded(
            child: Center(
              child: _jpeg == null
                  ? const CircularProgressIndicator()
                  : Transform.flip(
                      flipX: true, // selfie mirror
                      child: AspectRatio(
                        aspectRatio: _w / _h,
                        child: Stack(
                          fit: StackFit.expand,
                          children: [
                            Image.memory(_jpeg!, gaplessPlayback: true, fit: BoxFit.fill),
                            CustomPaint(painter: FaceMeshPainter(_landmarks, _edges)),
                          ],
                        ),
                      ),
                    ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (final s in steps) ...[
                      Icon(
                        _captures.containsKey(s) ? Icons.check_circle : Icons.radio_button_unchecked,
                        color: _captures.containsKey(s)
                            ? Colors.greenAccent
                            : (s == _step ? Colors.white : Colors.white38),
                      ),
                      const SizedBox(width: 4),
                      Text(_label(s), style: TextStyle(color: s == _step ? Colors.white : Colors.white38)),
                      const SizedBox(width: 16),
                    ],
                  ],
                ),
                const SizedBox(height: 8),
                LinearProgressIndicator(value: _progress, backgroundColor: Colors.white12),
                const SizedBox(height: 8),
                Text(_hint, style: const TextStyle(color: Colors.white, fontSize: 16)),
                Text('yaw ${_yaw.toStringAsFixed(0)}°', style: const TextStyle(color: Colors.white38, fontSize: 11)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _label(_Step s) => switch (s) {
        _Step.straight => 'Straight',
        _Step.left => 'Left',
        _Step.right => 'Right',
      };
}
