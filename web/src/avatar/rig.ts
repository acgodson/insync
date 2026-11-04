// Poses a VRM character's arms and fingers with two-bone IK. Works on the raw
// bones, so any VRM humanoid signs straight away.
import { Object3D, Quaternion, Vector3 } from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { SHAPES, type Curls, type Shape, type Vec3 } from "./signs";

export interface Pose {
  r: Vec3;
  l: Vec3;
  rs: Shape;
  ls: Shape;
}

interface FingerJoint {
  bone: Object3D;
  axis: Vector3;
  sign: number;
}

interface Arm {
  side: "left" | "right";
  sgn: 1 | -1;
  upper: Object3D;
  lower: Object3D;
  hand: Object3D;
  index: Object3D;
  middle: Object3D;
  little: Object3D;
  upperLen: number;
  lowerLen: number;
  palmSign: number;
  fingers: { thumb: boolean; joints: FingerJoint[] }[];
}

const FINGERS = ["Thumb", "Index", "Middle", "Ring", "Little"] as const;
const THUMB_BEND = [0.5, 0.6, 0.5];
const FINGER_BEND = [1.25, 1.45, 1.0];
const REFERENCE_SHOULDER = 1.438;

const worldPos = (o: Object3D) => o.getWorldPosition(new Vector3());

function rotateWorld(bone: Object3D, q: Quaternion) {
  const world = bone.getWorldQuaternion(new Quaternion());
  const parent = bone.parent!.getWorldQuaternion(new Quaternion());
  bone.quaternion.copy(parent.invert().multiply(q.clone().multiply(world)));
  bone.updateMatrixWorld(true);
}

function aim(bone: Object3D, from: Vector3, to: Vector3) {
  const origin = worldPos(bone);
  const a = from.clone().sub(origin).normalize();
  const b = to.clone().sub(origin).normalize();
  if (a.lengthSq() < 1e-8 || b.lengthSq() < 1e-8) return;
  rotateWorld(bone, new Quaternion().setFromUnitVectors(a, b));
}

export class SigningRig {
  readonly scale: number;
  private rest = new Map<Object3D, Quaternion>();
  private arms: { r: Arm; l: Arm };
  private cur: { r: Vector3; l: Vector3 };
  private curl: { r: Curls; l: Curls };
  private upperChest: Object3D | null;
  private head: Object3D | null;

  constructor(private vrm: VRM) {
    // We pose the raw bones ourselves, so stop the library overwriting them.
    vrm.humanoid.autoUpdateHumanBones = false;
    vrm.scene.traverse((n) => {
      if ((n as { isBone?: boolean }).isBone) this.rest.set(n, n.quaternion.clone());
    });
    vrm.scene.updateMatrixWorld(true);
    this.scale = worldPos(this.need("rightUpperArm")).y / REFERENCE_SHOULDER;
    this.upperChest = this.bone("upperChest") ?? this.bone("chest");
    this.head = this.bone("head");
    this.arms = { r: this.makeArm("right", 1), l: this.makeArm("left", -1) };
    this.cur = { r: new Vector3(), l: new Vector3() };
    this.curl = { r: [...SHAPES.rest], l: [...SHAPES.rest] };
  }

  private bone(name: string) {
    return this.vrm.humanoid.getRawBoneNode(name as VRMHumanBoneName);
  }

  private need(name: string) {
    const b = this.bone(name);
    if (!b) throw new Error(`This character has no ${name} bone`);
    return b;
  }

  /** Signing-space metres to world. VRM characters face +Z, so their right is -X. */
  private toWorld(p: Vec3) {
    return new Vector3(-p[0] * this.scale, p[1] * this.scale, p[2] * this.scale);
  }

  private makeArm(side: "left" | "right", sgn: 1 | -1): Arm {
    const upper = this.need(`${side}UpperArm`);
    const lower = this.need(`${side}LowerArm`);
    const hand = this.need(`${side}Hand`);
    const index = this.need(`${side}IndexProximal`);
    const middle = this.need(`${side}MiddleProximal`);
    const little = this.need(`${side}LittleProximal`);
    const handAt = worldPos(hand);
    const along = worldPos(middle).sub(handAt).normalize();
    const across = worldPos(index).sub(worldPos(little)).normalize();
    const normal = new Vector3().crossVectors(across, along);
    // Palms face down in a T-pose: that tells us which way "into the palm" is.
    const palmSign = normal.y < 0 ? 1 : -1;
    const palm = normal.clone().multiplyScalar(palmSign);

    const fingers = FINGERS.map((f) => {
      const thumb = f === "Thumb";
      const names = thumb ? ["Metacarpal", "Proximal", "Distal"] : ["Proximal", "Intermediate", "Distal"];
      const bones = names.map((n) => this.bone(`${side}${f}${n}`)).filter((b): b is Object3D => !!b);
      const axisWorld = thumb ? along : across;
      const joints = bones.map((bone) => ({
        bone,
        axis: axisWorld.clone().applyQuaternion(bone.getWorldQuaternion(new Quaternion()).invert()).normalize(),
        sign: 1,
      }));
      // Try a small bend and keep the direction that moves the fingertip into the palm.
      const first = joints[0];
      const rest = this.rest.get(first.bone)!;
      const tip = bones[bones.length - 1];
      const before = worldPos(tip);
      first.bone.quaternion.copy(rest).multiply(new Quaternion().setFromAxisAngle(first.axis, 0.5));
      first.bone.updateMatrixWorld(true);
      const moved = worldPos(tip).sub(before);
      first.bone.quaternion.copy(rest);
      first.bone.updateMatrixWorld(true);
      const sign = moved.dot(palm) >= 0 ? 1 : -1;
      joints.forEach((j) => (j.sign = sign));
      return { thumb, joints };
    });

    const upperAt = worldPos(upper);
    const lowerAt = worldPos(lower);
    return {
      side, sgn, upper, lower, hand, index, middle, little, palmSign, fingers,
      upperLen: upperAt.distanceTo(lowerAt),
      lowerLen: lowerAt.distanceTo(handAt),
    };
  }

  private poseArm(arm: Arm, target: Vector3, curls: Curls) {
    for (const b of [arm.upper, arm.lower, arm.hand]) b.quaternion.copy(this.rest.get(b)!);
    arm.upper.updateMatrixWorld(true);

    // Solve the elbow: a triangle of shoulder, elbow and wrist, with the elbow pushed down and out.
    const shoulder = worldPos(arm.upper);
    const dir = target.clone().sub(shoulder);
    const { upperLen: a, lowerLen: b } = arm;
    const reach = Math.max(0.05, Math.min(dir.length(), (a + b) * 0.995));
    dir.normalize();
    const angle = Math.acos(Math.max(-1, Math.min(1, (a * a + reach * reach - b * b) / (2 * a * reach))));
    const pole = this.toWorld([arm.sgn * 0.45, -1, -0.35]).normalize();
    pole.sub(dir.clone().multiplyScalar(pole.dot(dir))).normalize();
    const elbow = shoulder.clone().add(dir.clone().multiplyScalar(Math.cos(angle) * a)).add(pole.multiplyScalar(Math.sin(angle) * a));
    const wrist = shoulder.clone().add(dir.clone().multiplyScalar(reach));
    aim(arm.upper, worldPos(arm.lower), elbow);
    aim(arm.lower, worldPos(arm.hand), wrist);

    // Hand: fingers continue the forearm, tilted up a little, palm turned towards the viewer.
    const fingersDir = wrist.clone().sub(elbow).normalize().add(new Vector3(0, 0.55 * this.scale, 0)).normalize();
    const nowDir = worldPos(arm.middle).sub(worldPos(arm.hand)).normalize();
    rotateWorld(arm.hand, new Quaternion().setFromUnitVectors(nowDir, fingersDir));
    const across = worldPos(arm.index).sub(worldPos(arm.little)).normalize();
    const palm = new Vector3().crossVectors(across, fingersDir).multiplyScalar(arm.palmSign);
    const wanted = this.toWorld([-arm.sgn * 0.35, 0, 1]).normalize();
    palm.sub(fingersDir.clone().multiplyScalar(palm.dot(fingersDir))).normalize();
    wanted.sub(fingersDir.clone().multiplyScalar(wanted.dot(fingersDir))).normalize();
    let turn = Math.acos(Math.max(-1, Math.min(1, palm.dot(wanted))));
    if (new Vector3().crossVectors(palm, wanted).dot(fingersDir) < 0) turn = -turn;
    rotateWorld(arm.hand, new Quaternion().setFromAxisAngle(fingersDir, turn));

    arm.fingers.forEach((finger, i) => {
      const bend = finger.thumb ? THUMB_BEND : FINGER_BEND;
      finger.joints.forEach((j, k) => {
        j.bone.quaternion.copy(this.rest.get(j.bone)!).multiply(new Quaternion().setFromAxisAngle(j.axis, j.sign * curls[i] * bend[k]));
      });
    });
    arm.hand.updateMatrixWorld(true);
  }

  /** Jump straight to a pose, with no easing. */
  snap(pose: Pose) {
    this.cur.r.copy(this.toWorld(pose.r));
    this.cur.l.copy(this.toWorld(pose.l));
    this.curl.r = [...SHAPES[pose.rs]];
    this.curl.l = [...SHAPES[pose.ls]];
    this.apply(pose, 1, 0);
  }

  /** Ease towards a pose. `k` is how far to move this frame, 0 to 1; `t` is time in ms for idle sway. */
  apply(pose: Pose, k: number, t: number) {
    this.cur.r.lerp(this.toWorld(pose.r), k);
    this.cur.l.lerp(this.toWorld(pose.l), k);
    const r = SHAPES[pose.rs];
    const l = SHAPES[pose.ls];
    for (let i = 0; i < 5; i++) {
      this.curl.r[i] += (r[i] - this.curl.r[i]) * k;
      this.curl.l[i] += (l[i] - this.curl.l[i]) * k;
    }
    if (this.upperChest) {
      this.upperChest.quaternion.copy(this.rest.get(this.upperChest)!);
      this.upperChest.rotateX(Math.sin(t / 900) * 0.012);
    }
    if (this.head) {
      this.head.quaternion.copy(this.rest.get(this.head)!);
      this.head.rotateY(Math.sin(t / 2100) * 0.05);
      this.head.rotateX(0.04 + Math.sin(t / 2600) * 0.02);
    }
    this.vrm.scene.updateMatrixWorld(true);
    this.poseArm(this.arms.r, this.cur.r, this.curl.r);
    this.poseArm(this.arms.l, this.cur.l, this.curl.l);
  }
}
