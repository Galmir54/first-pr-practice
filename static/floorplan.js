// 3D-Grundriss (Three.js): lädt die STL-Datei der Wohnung und zeigt sie als "Puppenhaus"
// mit weichen Schatten, feinen Kantenlinien und einstellbarem Wandschnitt.
//
// Läuft unabhängig von app.js: ein MutationObserver beobachtet nur, ob #panel-floorplan
// sichtbar ist (gleiche .hidden-Klasse wie die anderen Tabs). Gerendert wird nur, wenn sich
// etwas ändert (Kamera bewegt, Regler, Größenänderung) - im Ruhezustand kostet die Ansicht
// praktisch keine Rechenleistung (wichtig für das Tablet).
import * as THREE from "three";
import { STLLoader } from "/static/vendor/three/jsm/loaders/STLLoader.js";
import { OrbitControls } from "/static/vendor/three/jsm/controls/OrbitControls.js";

const STL_URL = "/static/models/wohnung.stl";

// Die STL-Datei ist im Maßstab 1:100 exportiert (Gesamtgröße ~0,107 x 0,104 x 0,026 Einheiten,
// also rund 10,7 x 10,4 m Grundfläche bei 2,63 m Wandhöhe). Nach dem Skalieren gilt 1 Einheit = 1 m.
const MODEL_SCALE = 100;
// Waagerechte, nach oben zeigende Flächen unterhalb dieser Höhe sind Boden (Estrich ~0,1 m),
// knapp unter der Oberkante sind es Wandoberseiten, dazwischen z.B. Fensterbänke.
const FLOOR_MAX_Y = 0.3;
const WALL_TOP_BAND = 0.06;
const DEFAULT_CUT_M = 1.25;

const COLORS = {
  floor: 0xc79d6d, // helles Eichenholz
  wall: 0xf3f5f7,
  wallTop: 0xb4c2d0,
  edge: 0x0b141d,
  ground: 0x0d1c2a,
};

const panel = document.getElementById("panel-floorplan");
const container = document.getElementById("stlViewerContainer");
const hint = document.getElementById("stlViewerHint");
const toolbar = document.getElementById("fpToolbar");
const cutSlider = document.getElementById("fpCut");
const cutValue = document.getElementById("fpCutValue");
const viewButtons = [...document.querySelectorAll(".fp-btn[data-view]")];

let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let animationId = null;
let initialized = false;
let needsRender = true;

let bounds = null; // { height, radius, footprintRadius } in Metern
let clipPlane = null;

function setHint(text) {
  if (text) {
    hint.textContent = text;
    hint.classList.remove("hidden");
  } else {
    hint.classList.add("hidden");
  }
}

function requestRender() {
  needsRender = true;
}

function initScene() {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch {
    setHint("Die 3D-Ansicht wird von diesem Browser nicht unterstützt.");
    return false;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0); // Hintergrund-Verlauf kommt per CSS
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.localClippingEnabled = true;
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 600);

  scene.add(new THREE.HemisphereLight(0xdfeaff, 0x3a2d22, 1.05));
  const sun = new THREE.DirectionalLight(0xfff4e6, 2.1);
  sun.position.set(9, 16, 7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.03;
  scene.add(sun);
  scene.userData.sun = sun;

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.screenSpacePanning = false; // Verschieben entlang des Bodens statt "in die Höhe"
  controls.maxPolarAngle = Math.PI * 0.49; // nie unter den Boden schauen
  controls.addEventListener("start", () => viewButtons.forEach((b) => b.classList.remove("active")));

  clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 100); // behält alles unterhalb von y = constant

  loadModel();
  return true;
}

// Färbt jedes Dreieck nach Ausrichtung und Höhe ein (STL kennt keine Materialien).
function colorizeModel(geometry, height) {
  const floorColor = new THREE.Color(COLORS.floor);
  const wallColor = new THREE.Color(COLORS.wall);
  const wallTopColor = new THREE.Color(COLORS.wallTop);

  const pos = geometry.getAttribute("position");
  const colors = new Float32Array(pos.count * 3);
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const e1 = new THREE.Vector3();
  const e2 = new THREE.Vector3();
  const n = new THREE.Vector3();

  for (let i = 0; i < pos.count; i += 3) {
    a.fromBufferAttribute(pos, i);
    b.fromBufferAttribute(pos, i + 1);
    c.fromBufferAttribute(pos, i + 2);
    e1.subVectors(b, a);
    e2.subVectors(c, a);
    n.crossVectors(e1, e2);
    const doubleArea = n.length();
    n.divideScalar(doubleArea || 1);
    const longestEdge = Math.max(e1.length(), e2.length(), c.distanceTo(b));
    const width = longestEdge > 0 ? doubleArea / longestEdge : 0;

    // Hauchdünne Dreiecke haben eine unzuverlässige Normale (Rundungsrauschen) und würden sonst
    // als Wand durchrutschen und helle Striche auf dem Boden ergeben. Sind sie waagerecht
    // (nahezu keine Höhendifferenz), zählen sie als nach oben zeigend.
    const yMax = Math.max(a.y, b.y, c.y);
    const yRange = yMax - Math.min(a.y, b.y, c.y);
    const flat = yRange < 0.01;
    const facesUp = n.y > 0.7 || (flat && n.y > -0.7);
    // Bodenstufen (10 vs. 12 cm) erzeugen lange, flache Dreiecke mit 2 cm Höhenunterschied, deren
    // Normale beliebig kippen kann: alles, was ganz unten liegt und fast flach ist, gilt als Boden.
    const lowAndNearlyFlat = yMax < FLOOR_MAX_Y && yRange < 0.05 && n.y > -0.7;

    // Das Modell enthält einige Dutzend lange, nur Millimeter bis Zentimeter breite Dreiecke, die
    // von Möbelhöhe bis zum Boden reichen (Fehler in der Dreiecks-Aufteilung). Als weiße Striche
    // würden sie auf dem Holzboden auffallen, daher bekommen sie die Bodenfarbe.
    const floorSliver = width < 0.04 && longestEdge > 0.8 && Math.min(a.y, b.y, c.y) < FLOOR_MAX_Y && yMax < 1.0;

    let color = wallColor;
    if (lowAndNearlyFlat || floorSliver) {
      color = floorColor;
    } else if (facesUp) {
      const y = (a.y + b.y + c.y) / 3;
      if (y < FLOOR_MAX_Y) color = floorColor;
      else if (y > height - WALL_TOP_BAND) color = wallTopColor;
    }
    for (let v = 0; v < 3; v++) {
      colors[(i + v) * 3] = color.r;
      colors[(i + v) * 3 + 1] = color.g;
      colors[(i + v) * 3 + 2] = color.b;
    }
  }
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
}

function loadModel() {
  setHint("3D-Modell wird geladen …");
  new STLLoader().load(
    STL_URL,
    (geometry) => {
      // CAD-Modelle haben "oben" auf der Z-Achse, three.js auf Y -> aufrichten, auf Meter
      // skalieren, mittig auf den Ursprung setzen und den Boden auf y = 0 legen.
      geometry.scale(MODEL_SCALE, MODEL_SCALE, MODEL_SCALE);
      geometry.rotateX(-Math.PI / 2);
      geometry.computeBoundingBox();
      const bb = geometry.boundingBox;
      geometry.translate(-(bb.min.x + bb.max.x) / 2, -bb.min.y, -(bb.min.z + bb.max.z) / 2);
      geometry.computeBoundingBox();

      const size = new THREE.Vector3();
      geometry.boundingBox.getSize(size);
      bounds = {
        height: size.y,
        radius: size.length() / 2,
        footprintRadius: Math.hypot(size.x, size.z) / 2,
        size: size.clone(),
      };

      colorizeModel(geometry, size.y);

      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.78,
        metalness: 0.0,
        side: THREE.DoubleSide,
        clippingPlanes: [clipPlane],
        clipShadows: true,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.renderOrder = 6;
      scene.add(mesh);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry, 30),
        new THREE.LineBasicMaterial({
          color: COLORS.edge,
          transparent: true,
          opacity: 0.4,
          clippingPlanes: [clipPlane],
        })
      );
      edges.renderOrder = 7;
      scene.add(edges);

      // Boden-Scheibe mit Schattenempfang und feinem Raster
      const ground = new THREE.Mesh(
        new THREE.CircleGeometry(bounds.radius * 2.4, 72),
        new THREE.MeshStandardMaterial({ color: COLORS.ground, roughness: 1, metalness: 0 })
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = -0.03;
      ground.receiveShadow = true;
      scene.add(ground);

      const grid = new THREE.GridHelper(bounds.radius * 4.4, 44, 0x1d4a66, 0x12293a);
      grid.position.y = -0.02;
      grid.material.transparent = true;
      grid.material.opacity = 0.55;
      scene.add(grid);

      // Schatten-Kamera passend zur Modellgröße
      const sun = scene.userData.sun;
      const r = bounds.radius * 1.25;
      Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 1, far: bounds.radius * 6 });
      sun.shadow.camera.updateProjectionMatrix();

      controls.minDistance = bounds.radius * 0.35;
      controls.maxDistance = bounds.radius * 6;

      // Schnitt-Regler: ganz rechts = kein Schnitt
      cutSlider.min = "0.3";
      cutSlider.max = String(bounds.height.toFixed(2));
      cutSlider.value = String(DEFAULT_CUT_M);
      applyCut(DEFAULT_CUT_M);

      setView("iso");
      toolbar.classList.remove("hidden");
      setHint(null);

      // Zugriff für spätere Erweiterungen (Marker für Lampen/Steckdosen/Temperatur) und zum Testen.
      window.floorplan = { THREE, renderer, scene, camera, controls, bounds, requestRender };
    },
    undefined,
    () => {
      setHint(
        "Kein 3D-Modell gefunden. Lege eine STL-Datei unter static/models/wohnung.stl ab, sobald sie bereitsteht."
      );
    }
  );
}

function applyCut(heightM) {
  const full = bounds && heightM >= bounds.height - 0.005;
  const y = full ? bounds.height + 1 : heightM; // über der Oberkante = kein sichtbarer Schnitt
  clipPlane.constant = y;
  cutValue.textContent = full ? "ganze Wände" : `${heightM.toFixed(2).replace(".", ",")} m`;
  requestRender();
}

function setView(kind) {
  if (!bounds) return;
  const vfov = THREE.MathUtils.degToRad(camera.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
  const fit = (radius) => (radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.08;

  controls.target.set(0, bounds.height * 0.2, 0);
  if (kind === "top") {
    // Leicht nach +z versetzt: legt fest, dass "oben" im Bild die Plan-Nordrichtung ist (sonst
    // dreht die Kamera den Plan beliebig, z.B. um 45°).
    // Rechteck statt Kreis einpassen; die Wandoberkanten liegen näher an der Kamera, daher + Höhe.
    const tanV = Math.tan(vfov / 2);
    const tanH = Math.tan(hfov / 2);
    const distance = Math.max(bounds.size.z / 2 / tanV, bounds.size.x / 2 / tanH) + bounds.height;
    camera.position.set(0, distance * 1.1, 0.001);
  } else {
    const azimuth = THREE.MathUtils.degToRad(38);
    const elevation = THREE.MathUtils.degToRad(50);
    const d = fit(bounds.radius);
    camera.position.set(
      controls.target.x + d * Math.cos(elevation) * Math.sin(azimuth),
      controls.target.y + d * Math.sin(elevation),
      controls.target.z + d * Math.cos(elevation) * Math.cos(azimuth)
    );
  }
  camera.near = 0.1;
  camera.far = bounds.radius * 40;
  camera.updateProjectionMatrix();
  controls.update();
  viewButtons.forEach((b) => b.classList.toggle("active", b.dataset.view === kind));
  requestRender();
}

function resize() {
  if (!renderer || !container) return;
  const w = container.clientWidth;
  const h = container.clientHeight;
  if (w === 0 || h === 0) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  requestRender();
}

function animate() {
  animationId = requestAnimationFrame(animate);
  const moved = controls.update();
  if (moved || needsRender) {
    renderer.render(scene, camera);
    needsRender = false;
  }
}

function startViewer() {
  if (!initialized) {
    initialized = true;
    if (!initScene()) return;
  }
  if (!renderer) return;
  resize();
  requestRender();
  if (animationId === null) animate();
}

function stopViewer() {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }
}

viewButtons.forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.getElementById("fpReset").addEventListener("click", () => {
  if (!bounds) return;
  cutSlider.value = String(DEFAULT_CUT_M);
  applyCut(DEFAULT_CUT_M);
  setView("iso");
});
cutSlider.addEventListener("input", () => applyCut(parseFloat(cutSlider.value)));

const observer = new MutationObserver(() => {
  if (panel.classList.contains("hidden")) {
    stopViewer();
  } else {
    startViewer();
  }
});
observer.observe(panel, { attributes: true, attributeFilter: ["class"] });

window.addEventListener("resize", () => {
  if (!panel.classList.contains("hidden")) resize();
});

if (!panel.classList.contains("hidden")) {
  startViewer();
}
