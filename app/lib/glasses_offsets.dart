// Glasses camera offsets relative to head centre (metres, head frame: +x right, +y up, +z forward)
// TODO: measure on the actual Ray-Ban Meta Gen 1 frames; these are placeholders.
class GlassesOffsets {
  static const double cameraX = 0.055; // TODO: measure (left temple camera, ~55 mm from centre)
  static const double cameraY = 0.010; // TODO: measure
  static const double cameraZ = 0.080; // TODO: measure (in front of head centre)
  static const double cameraPitchDeg = 0.0; // TODO: measure
  static const double cameraYawDeg = 0.0; // TODO: measure
}
