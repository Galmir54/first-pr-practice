// 3D-Grundriss-Ansicht (Three.js). Lädt eine STL-Datei und zeigt sie drehbar/zoombar an.
// Läuft unabhängig von app.js: beobachtet per MutationObserver nur, ob #panel-floorplan
// gerade sichtbar ist (gleiche .hidden-Klasse wie die anderen Tabs), und startet/stoppt
// die Render-Loop entsprechend, statt dauerhaft im Hintergrund zu rendern.
import * as THREE from "three";
import { STLLoader } from "/static/vendor/three/jsm/loaders/STLLoader.js";
import { OrbitControls } from "/static/vendor/three/jsm/controls/OrbitControls.js";

const STL_URL = "/static/models/wohnung.stl";

const panel = document.getElementById("panel-floorplan");
const container = document.getElementById("stlViewerContainer");
const hint = document.getElementById("stlViewerHint");

let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let animationId = null;
let initialized = false;

function setHint(text) {
  if (text) {
    hint.textContent = text;
    hint.classList.remove("hidden");
  } else {
    hint.classList.add("hidden");
  }
}

function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05080d);

  camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100000);
  camera.position.set(300, 300, 300);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(1, 1.5, 1);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.35);
  fill.position.set(-1, -0.5, -1);
  scene.add(fill);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  loadModel();
}

// STL-Dateien enthalten keine Farb-/Materialinfos, nur nackte Dreiecke. Um trotzdem
// Holzboden + weiße Wände darzustellen, wird jedes Dreieck anhand der Ausrichtung
// seiner Flächennormale eingefärbt: die Achse mit der kleinsten Ausdehnung der
// Bounding-Box gilt als "oben" (bei einem Wohnungs-Grundriss ist das fast immer die
// Deckenhöhe, deutlich kleiner als Länge/Breite). Zeigt die Normale stark entlang
// dieser Achse nach oben, ist es eine Bodenfläche → Holzton, sonst Wand/Decke → weiß.
function colorizeByOrientation(geometry) {
  geometry.computeBoundingBox();
  const size = new THREE.Vector3();
  geometry.boundingBox.getSize(size);
  const upAxis = [size.x, size.y, size.z].indexOf(Math.min(size.x, size.y, size.z));

  const floorColor = new THREE.Color(0x9c6b3e);
  const wallColor = new THREE.Color(0xf1efe9);

  const pos = geometry.getAttribute("position");
  const colors = new Float32Array(pos.count * 3);
  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const vC = new THREE.Vector3();
  const edge1 = new THREE.Vector3();
  const edge2 = new THREE.Vector3();
  const normal = new THREE.Vector3();

  for (let base = 0; base < pos.count; base += 3) {
    vA.fromBufferAttribute(pos, base);
    vB.fromBufferAttribute(pos, base + 1);
    vC.fromBufferAttribute(pos, base + 2);
    edge1.subVectors(vB, vA);
    edge2.subVectors(vC, vA);
    normal.crossVectors(edge1, edge2).normalize();

    const isFloor = normal.getComponent(upAxis) > 0.7;
    const color = isFloor ? floorColor : wallColor;

    for (let v = 0; v < 3; v++) {
      colors[(base + v) * 3] = color.r;
      colors[(base + v) * 3 + 1] = color.g;
      colors[(base + v) * 3 + 2] = color.b;
    }
  }

  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
}

function loadModel() {
  setHint("3D-Modell wird geladen …");
  const loader = new STLLoader();
  loader.load(
    STL_URL,
    (geometry) => {
      geometry.center();
      colorizeByOrientation(geometry);

      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        metalness: 0.05,
        roughness: 0.85,
      });
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      const size = new THREE.Vector3();
      geometry.boundingBox.getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z, 1);

      camera.near = maxDim / 100;
      camera.far = maxDim * 100;
      camera.position.set(maxDim, maxDim, maxDim);
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();

      setHint(null);
    },
    undefined,
    () => {
      setHint(
        "Kein 3D-Modell gefunden. Lege eine STL-Datei unter static/models/wohnung.stl ab, sobald sie bereitsteht."
      );
    }
  );
}

function resize() {
  if (!renderer || !container) return;
  const w = container.clientWidth;
  const h = container.clientHeight;
  if (w === 0 || h === 0) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

function animate() {
  animationId = requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function startViewer() {
  if (!initialized) {
    initScene();
    initialized = true;
  }
  resize();
  if (animationId === null) {
    animate();
  }
}

function stopViewer() {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }
}

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
