// The full-bleed 3D stage: loads the interpreter, plays signs and frames the shot.
import { AmbientLight, Box3, Color, DirectionalLight, MathUtils, PerspectiveCamera, SRGBColorSpace, Scene, WebGLRenderer, type Mesh, type Texture } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { SigningRig, type Pose } from "./rig";
import { SPOTS, along, buildTimeline, type TimelineItem } from "./signs";

const REST: Pose = { r: SPOTS.restR, l: SPOTS.restL, rs: "rest", ls: "rest" };
const FOV = 24;

interface SkinMaterial {
  color: Color;
  shadeColorFactor: Color;
  map: Texture | null;
  isOutline?: boolean;
}
interface SkinPart {
  mat: SkinMaterial;
  lit: Color;
  shade: Color;
}

/** The middle colour of a skin texture, in linear light. */
function typicalColor(map: Texture | null): Color | null {
  const image = map?.image as CanvasImageSource | undefined;
  if (!image) return null;
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(image, 0, 0, size, size);
  const px = ctx.getImageData(0, 0, size, size).data;
  const channels: number[][] = [[], [], []];
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] < 200) continue;
    for (let c = 0; c < 3; c++) channels[c].push(px[i + c]);
  }
  if (!channels[0].length) return null;
  const [r, g, b] = channels.map((v) => v.sort((x, y) => x - y)[v.length >> 1] / 255);
  return new Color().setRGB(r, g, b, SRGBColorSpace);
}

export class Stage {
  /** Called whenever the sign being played changes. */
  onProgress: (items: TimelineItem[], index: number) => void = () => {};

  private renderer: WebGLRenderer;
  private scene = new Scene();
  private camera = new PerspectiveCamera(FOV, 1, 0.05, 30);
  private lastFrame = performance.now();
  private vrm: VRM | null = null;
  private rig: SigningRig | null = null;
  private items: TimelineItem[] = [];
  private index = -1;
  private itemTime = 0;
  private insets = { top: 56, bottom: 200, left: 0 };
  private frameTop = 1.6;
  private frameBottom = 0.8;
  private frameWidth = 1;
  private nextBlink = 3000;
  private blink = 0;
  private still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  private speed = 1;
  private skin: SkinPart[] = [];
  private skinBase: Color | null = null;

  constructor(private canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    this.scene.add(new AmbientLight(0xffffff, 1.3));
    const key = new DirectionalLight(0xffffff, 1.9);
    key.position.set(1, 2, 3);
    this.scene.add(key);
    new ResizeObserver(() => this.fit()).observe(canvas);
    this.renderer.setAnimationLoop(() => this.frame());
  }

  async load(url: string, onPercent: (p: number) => void) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url, (e) => {
      if (e.total) onPercent(Math.round((e.loaded / e.total) * 100));
    });
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) throw new Error("That file isn't a VRM character");
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
      this.vrm = null;
      this.rig = null;
    }
    VRMUtils.rotateVRM0(vrm); // older exports face the other way
    vrm.scene.traverse((n) => (n.frustumCulled = false));
    this.scene.add(vrm.scene);
    vrm.scene.updateMatrixWorld(true);

    const size = new Box3().setFromObject(vrm.scene);
    const rig = new SigningRig(vrm);
    this.frameTop = size.max.y + 0.03 * rig.scale;
    this.frameBottom = 0.98 * rig.scale; // head to waist: hands and face stay large
    this.frameWidth = 0.92 * rig.scale;
    rig.snap(REST);
    this.vrm = vrm;
    this.rig = rig;
    this.collectSkin(vrm);
    this.fit();
  }

  get ready() {
    return !!this.rig;
  }

  /** False when the character's materials aren't labelled as skin, so tones can't apply. */
  get canTone() {
    return !!this.skinBase;
  }

  // VRoid labels skin materials with _SKIN. We tint against the colour they were painted.
  private collectSkin(vrm: VRM) {
    this.skin = [];
    this.skinBase = null;
    vrm.scene.traverse((n) => {
      const mesh = n as Mesh;
      if (!mesh.isMesh) return;
      for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        const mat = m as unknown as SkinMaterial;
        if (!/_SKIN/i.test(m.name) || mat.isOutline || !mat.shadeColorFactor) continue;
        if (this.skin.some((p) => p.mat === mat)) continue;
        this.skin.push({ mat, lit: mat.color.clone(), shade: mat.shadeColorFactor.clone() });
        if (/body/i.test(m.name) || !this.skinBase) this.skinBase = typicalColor(mat.map) ?? this.skinBase;
      }
    });
  }

  /** Tint the interpreter's skin to a sRGB colour, or null for how it was designed. */
  setTone(hex: number | null) {
    const base = this.skinBase;
    if (!base) return;
    const target = hex === null ? base : new Color(hex);
    const ratio = new Color(target.r / base.r, target.g / base.g, target.b / base.b);
    for (const part of this.skin) {
      part.mat.color.copy(part.lit).multiply(ratio);
      part.mat.shadeColorFactor.copy(part.shade).multiply(ratio);
    }
  }

  setSpeed(speed: number) {
    this.speed = speed;
  }

  /** Show the stage inside another element, like the onboarding preview. */
  mount(slot: HTMLElement) {
    slot.prepend(this.canvas);
    this.setInsets(12, 12);
  }

  /** Put the stage back behind the app. Call setInsets afterwards. */
  unmount(app: HTMLElement) {
    app.prepend(this.canvas);
  }

  /** Adds to what's playing, so a new sentence never cuts off one Alice is still watching. */
  enqueue(signs: string[]) {
    if (this.index < 0) return this.play(signs, []);
    this.items.push(...buildTimeline(signs, []));
    this.onProgress(this.items, this.index);
  }

  play(signs: string[], fingerspell: string[]) {
    this.items = buildTimeline(signs, fingerspell);
    this.index = this.items.length ? 0 : -1;
    this.itemTime = 0;
    this.onProgress(this.items, this.index);
  }

  /** The screen space the shot must stay clear of, in CSS pixels. A negative `left` keeps clear of the right edge. */
  setInsets(top: number, bottom: number, left = 0) {
    this.insets = { top, bottom, left };
    this.fit();
  }

  // Keep head to hips between the top bar and the captions, so subtitles never cover the hands.
  private fit() {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    const clearH = Math.max(1, h - this.insets.top - this.insets.bottom);
    const perPx = Math.max((this.frameTop - this.frameBottom) / clearH, this.frameWidth / Math.max(1, w - Math.abs(this.insets.left)));
    const viewH = h * perPx;
    const centreY = this.frameTop + this.insets.top * perPx - viewH / 2;
    const dist = viewH / 2 / Math.tan(MathUtils.degToRad(FOV / 2));
    this.camera.aspect = w / h;
    // Sliding the camera left moves the figure right, into the space beside any text.
    const x = (-this.insets.left / 2) * perPx;
    this.camera.position.set(x, centreY, dist);
    this.camera.lookAt(x, centreY, 0);
    this.camera.updateProjectionMatrix();
  }

  private currentPose(): Pose {
    const item = this.items[this.index];
    if (!item) return REST;
    const p = Math.min(1, this.itemTime / item.ms);
    const { def } = item;
    return {
      r: along(def.r, p, item.kind === "letter"),
      l: def.l ? along(def.l, p) : SPOTS.restL,
      rs: def.s,
      ls: def.l ? (def.ls ?? "flat") : "rest",
    };
  }

  private step(ms: number) {
    if (this.index < 0) return;
    this.itemTime += ms;
    if (this.itemTime >= this.items[this.index].ms) {
      this.itemTime = 0;
      this.index = this.index + 1 < this.items.length ? this.index + 1 : -1;
      this.onProgress(this.items, this.index);
    }
  }

  private blinkFace(ms: number, t: number) {
    const face = this.vrm?.expressionManager;
    if (!face) return;
    if (t > this.nextBlink) {
      this.blink = 1;
      this.nextBlink = t + 2500 + Math.random() * 3000;
    }
    this.blink = Math.max(0, this.blink - ms / 140);
    face.setValue("blink", Math.sin(this.blink * Math.PI));
  }

  private frame() {
    const t = performance.now();
    const ms = Math.min(100, t - this.lastFrame);
    this.lastFrame = t;
    this.step(ms * this.speed); // the signs still play in order with no model loaded
    if (this.rig && this.vrm) {
      this.rig.apply(this.currentPose(), 1 - Math.exp((-ms / 1000) * 11 * this.speed), this.still ? 0 : t);
      this.blinkFace(ms, t);
      this.vrm.update(ms / 1000); // expressions and hair physics
    }
    this.renderer.render(this.scene, this.camera);
  }
}
