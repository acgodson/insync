import 'dart:typed_data';
import 'dart:ui' show PointMode;

import 'package:flutter/material.dart';

// Translucent wireframe over normalised face landmarks (painter size = image size)
class FaceMeshPainter extends CustomPainter {
  FaceMeshPainter(this.landmarks, this.edges, {this.color = const Color(0x9900E5FF)});

  final Float32List? landmarks; // 478 * 3
  final List<int> edges; // flat pairs
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final pts = landmarks;
    if (pts == null || edges.isEmpty) return;
    final paint = Paint()
      ..color = color
      ..strokeWidth = 0.8
      ..style = PaintingStyle.stroke;
    final lines = Float32List(edges.length * 2);
    for (var i = 0; i + 1 < edges.length; i += 2) {
      final a = edges[i] * 3, b = edges[i + 1] * 3;
      lines[i * 2] = pts[a] * size.width;
      lines[i * 2 + 1] = pts[a + 1] * size.height;
      lines[i * 2 + 2] = pts[b] * size.width;
      lines[i * 2 + 3] = pts[b + 1] * size.height;
    }
    canvas.drawRawPoints(PointMode.lines, lines, paint);
  }

  @override
  bool shouldRepaint(FaceMeshPainter old) => old.landmarks != landmarks || old.edges != edges;
}
