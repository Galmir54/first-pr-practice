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
// Standardmäßig ganze Wände (kein Schnitt); der Regler "Wandschnitt" kürzt sie bei Bedarf.
const DEFAULT_CUT_M = Infinity;

const COLORS = {
  wall: 0xf7f5f1, // warmes Weiß
  wallTop: 0xeef1f4,
  edge: 0x1a2a38,
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
  renderer.toneMappingExposure = 1.12;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.localClippingEnabled = true;
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 600);

  // helles, freundliches Licht: kräftiges Umgebungslicht, weiche Sonne von vorn-rechts, Gegenlicht ohne Schatten
  scene.add(new THREE.HemisphereLight(0xeaf2ff, 0x6b5a4a, 1.75));
  const fill = new THREE.DirectionalLight(0xdbe8ff, 0.7);
  fill.position.set(-10, 9, -6);
  scene.add(fill);
  const sun = new THREE.DirectionalLight(0xfff1de, 1.35);
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

// Zerlegt das STL-Modell in Boden (bekommt eine Holzdiele-Textur) und den Rest (Wände + Möbel).
//
// STL kennt weder Materialien noch Objekte, deshalb wird aus der Geometrie geraten:
//  - Boden: waagerechte, nach oben zeigende Flächen ganz unten.
//  - Wand: alles, was im Grundriss auf den (leicht verbreiterten) Wandoberkanten liegt.
//  - Möbel: der Rest zwischen den Wänden. Zusammenhängende Flächen ergeben je ein Möbelstück, das
//    nach Höhe und Grundfläche eine Farbe bekommt (Schrank = helles Holz, Tisch = Nussbaum, Bett/
//    Sofa = Stoff ...).
const GRID_CELL = 0.05;
const WALL_DILATE_CELLS = 2; // 10 cm: Wandflächen liegen direkt am Rand der Oberkante
const FURNITURE_MAX_Y = 2.3; // höhere Teile ohne Wandoberkante sind trotzdem Wand
const FLOOR_TILE_M = 1.2; // so viele Meter deckt eine Wiederholung der Dielentextur ab

const FURNITURE_FABRICS = [0x7f95aa, 0xc47a5e, 0x8fa88a, 0x6c7d92, 0xd0b48a];
const FURNITURE_SMALL = [0x5d6b7a, 0xb98b6b, 0x8da38b, 0x6f8ea8, 0xc9b79c, 0x4a5563];

function hash01(a, b) {
  const s = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function furnitureColor(box) {
  const dx = box.max.x - box.min.x;
  const dz = box.max.z - box.min.z;
  const footprint = dx * dz;
  const top = box.max.y;
  const r = hash01((box.min.x + box.max.x) * 7.3, (box.min.z + box.max.z) * 5.1);
  const pick = (list) => list[Math.floor(r * list.length) % list.length];
  if (top > 1.5 && footprint > 0.12) return 0xe6d8bf; // Schrank, Regal, Kühlschrank: helle Eiche
  if (top > 0.7 && top <= 1.2 && footprint > 0.25) return r < 0.4 ? 0xd8d3cb : 0x9a7551; // Arbeitsplatte oder Tisch
  if (top <= 0.8 && footprint > 1.0) return pick(FURNITURE_FABRICS); // Bett, Sofa
  return pick(FURNITURE_SMALL);
}

function rasterTriangle(mask, gw, gh, minX, minZ, ax, az, bx, bz, cx, cz) {
  const toCell = (v, min) => (v - min) / GRID_CELL;
  const pax = toCell(ax, minX), paz = toCell(az, minZ);
  const pbx = toCell(bx, minX), pbz = toCell(bz, minZ);
  const pcx = toCell(cx, minX), pcz = toCell(cz, minZ);
  const den = (pbz - pcz) * (pax - pcx) + (pcx - pbx) * (paz - pcz);
  const x0 = Math.max(0, Math.floor(Math.min(pax, pbx, pcx)));
  const x1 = Math.min(gw - 1, Math.ceil(Math.max(pax, pbx, pcx)));
  const z0 = Math.max(0, Math.floor(Math.min(paz, pbz, pcz)));
  const z1 = Math.min(gh - 1, Math.ceil(Math.max(paz, pbz, pcz)));
  if (Math.abs(den) < 1e-9) return; // entartet: keine Fläche
  for (let z = z0; z <= z1; z++) {
    for (let x = x0; x <= x1; x++) {
      const px = x + 0.5, pz = z + 0.5;
      const l1 = ((pbz - pcz) * (px - pcx) + (pcx - pbx) * (pz - pcz)) / den;
      const l2 = ((pcz - paz) * (px - pcx) + (pax - pcx) * (pz - pcz)) / den;
      const l3 = 1 - l1 - l2;
      if (l1 >= -0.25 && l2 >= -0.25 && l3 >= -0.25) mask[z * gw + x] = 1;
    }
  }
}

function dilateMask(mask, gw, gh, radius) {
  const tmp = new Uint8Array(mask.length);
  for (let z = 0; z < gh; z++) {
    for (let x = 0; x < gw; x++) {
      if (!mask[z * gw + x]) continue;
      for (let dx = -radius; dx <= radius; dx++) {
        const xx = x + dx;
        if (xx >= 0 && xx < gw) tmp[z * gw + xx] = 1;
      }
    }
  }
  const out = new Uint8Array(mask.length);
  for (let z = 0; z < gh; z++) {
    for (let x = 0; x < gw; x++) {
      if (!tmp[z * gw + x]) continue;
      for (let dz = -radius; dz <= radius; dz++) {
        const zz = z + dz;
        if (zz >= 0 && zz < gh) out[zz * gw + x] = 1;
      }
    }
  }
  return out;
}

function subsetGeometry(source, triangles) {
  const geometry = new THREE.BufferGeometry();
  for (const name of ["position", "normal"]) {
    const src = source.getAttribute(name).array;
    const out = new Float32Array(triangles.length * 9);
    triangles.forEach((t, i) => out.set(src.subarray(t * 9, t * 9 + 9), i * 9));
    geometry.setAttribute(name, new THREE.BufferAttribute(out, 3));
  }
  return geometry;
}

function buildModelGeometries(source, height) {
  const pos = source.getAttribute("position");
  const triCount = pos.count / 3;
  const bb = source.boundingBox;
  const minX = bb.min.x - 0.3;
  const minZ = bb.min.z - 0.3;
  const gw = Math.ceil((bb.max.x - minX + 0.3) / GRID_CELL) + 1;
  const gh = Math.ceil((bb.max.z - minZ + 0.3) / GRID_CELL) + 1;

  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const e1 = new THREE.Vector3();
  const e2 = new THREE.Vector3();
  const n = new THREE.Vector3();

  // 0 = Wand, 1 = Boden, 2 = Möbel-Kandidat
  const kind = new Uint8Array(triCount);
  const cellOf = new Int32Array(triCount);
  const wallMask = new Uint8Array(gw * gh);

  for (let t = 0; t < triCount; t++) {
    const i = t * 3;
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
    const yMax = Math.max(a.y, b.y, c.y);
    const yMin = Math.min(a.y, b.y, c.y);
    const yRange = yMax - yMin;
    const flat = yRange < 0.01;
    const facesUp = n.y > 0.7 || (flat && n.y > -0.7);
    const lowAndNearlyFlat = yMax < FLOOR_MAX_Y && yRange < 0.05 && n.y > -0.7;
    // lange, hauchdünne Dreiecke (Fehler in der Aufteilung) würden auf dem Boden als Striche auffallen
    const floorSliver = width < 0.04 && longestEdge > 0.8 && yMin < FLOOR_MAX_Y && yMax < 1.0;

    const cx = (a.x + b.x + c.x) / 3;
    const cz = (a.z + b.z + c.z) / 3;
    cellOf[t] = Math.max(0, Math.min(gh - 1, Math.floor((cz - minZ) / GRID_CELL))) * gw +
      Math.max(0, Math.min(gw - 1, Math.floor((cx - minX) / GRID_CELL)));

    if (lowAndNearlyFlat || floorSliver || (facesUp && (yMin + yMax) / 2 < FLOOR_MAX_Y)) {
      kind[t] = 1;
    } else {
      kind[t] = 2;
      if (facesUp && yMin > height - 0.1) {
        rasterTriangle(wallMask, gw, gh, minX, minZ, a.x, a.z, b.x, b.z, c.x, c.z);
      }
    }
  }

  const wallZone = dilateMask(wallMask, gw, gh, WALL_DILATE_CELLS);
  for (let t = 0; t < triCount; t++) {
    if (kind[t] === 2 && wallZone[cellOf[t]]) kind[t] = 0;
  }

  // Möbelstücke = zusammenhängende Dreiecksgruppen außerhalb der Wände
  const parent = new Map();
  const find = (k) => {
    let root = k;
    while (parent.get(root) !== root) root = parent.get(root);
    while (parent.get(k) !== root) {
      const next = parent.get(k);
      parent.set(k, root);
      k = next;
    }
    return root;
  };
  const key = (i) => `${Math.round(pos.getX(i) * 500)},${Math.round(pos.getY(i) * 500)},${Math.round(pos.getZ(i) * 500)}`;
  const triKeys = new Map();
  for (let t = 0; t < triCount; t++) {
    if (kind[t] !== 2) continue;
    const k0 = key(t * 3);
    const k1 = key(t * 3 + 1);
    const k2 = key(t * 3 + 2);
    triKeys.set(t, k0);
    for (const k of [k0, k1, k2]) if (!parent.has(k)) parent.set(k, k);
    parent.set(find(k1), find(k0));
    parent.set(find(k2), find(k0));
  }
  const groups = new Map();
  for (const [t, k0] of triKeys) {
    const root = find(k0);
    if (!groups.has(root)) groups.set(root, { tris: [], box: new THREE.Box3() });
    const g = groups.get(root);
    g.tris.push(t);
    for (let v = 0; v < 3; v++) g.box.expandByPoint(a.fromBufferAttribute(pos, t * 3 + v));
  }

  const wallColor = new THREE.Color(COLORS.wall);
  const wallTopColor = new THREE.Color(COLORS.wallTop);
  const triColor = new Array(triCount);
  for (let t = 0; t < triCount; t++) {
    if (kind[t] === 0) triColor[t] = wallColor;
  }
  for (const g of groups.values()) {
    const isFurniture = g.box.max.y < FURNITURE_MAX_Y && g.tris.length > 0;
    const color = isFurniture ? new THREE.Color(furnitureColor(g.box)) : wallColor;
    for (const t of g.tris) triColor[t] = color;
  }

  // Wandoberkanten etwas dunkler absetzen
  for (let t = 0; t < triCount; t++) {
    if (kind[t] !== 0) continue;
    const i = t * 3;
    a.fromBufferAttribute(pos, i);
    b.fromBufferAttribute(pos, i + 1);
    c.fromBufferAttribute(pos, i + 2);
    n.crossVectors(e1.subVectors(b, a), e2.subVectors(c, a)).normalize();
    if (n.y > 0.7 && (a.y + b.y + c.y) / 3 > height - WALL_TOP_BAND) triColor[t] = wallTopColor;
  }

  const floorTris = [];
  const restTris = [];
  for (let t = 0; t < triCount; t++) (kind[t] === 1 ? floorTris : restTris).push(t);

  const floorGeometry = subsetGeometry(source, floorTris);

  const restGeometry = subsetGeometry(source, restTris);
  const colors = new Float32Array(restTris.length * 9);
  restTris.forEach((t, i) => {
    const col = triColor[t] || wallColor;
    for (let v = 0; v < 3; v++) {
      colors[i * 9 + v * 3] = col.r;
      colors[i * 9 + v * 3 + 1] = col.g;
      colors[i * 9 + v * 3 + 2] = col.b;
    }
  });
  restGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  // Teppiche unter Betten, Sofas und Esstischen (große Möbel)
  const rugs = [];
  for (const g of groups.values()) {
    const bx = g.box;
    if (bx.max.y >= FURNITURE_MAX_Y) continue;
    const dx = bx.max.x - bx.min.x;
    const dz = bx.max.z - bx.min.z;
    const footprint = dx * dz;
    const soft = bx.max.y <= 0.8 && footprint > 1.0;
    const table = bx.max.y > 0.65 && bx.max.y <= 1.2 && footprint > 1.2;
    // zu große "Möbel" sind in Wirklichkeit mehrere zusammenhängende Teile: dafür kein Teppich
    if ((soft || table) && dx < 2.6 && dz < 2.6 && footprint < 4.5) rugs.push({ box: bx.clone(), seed: hash01(bx.min.x * 3.1, bx.min.z * 2.7) });
  }

  return { floorGeometry, restGeometry, rugs, grid: { wallZone, minX, minZ, gw, gh } };
}

// ---------------------------------------------------------------------------------------------
// Bodenbeläge je Raum: Küche und Bad bekommen Fliesen (Hexagon-Mosaik), alles andere Holzdielen.
// Das Modell kennt keine Räume. Deshalb wird von jedem benannten Raumschild aus (kürzester Weg
// um die Wände herum) der Boden dem nächsten Raum zugeordnet, Fliesenräume nur im Umkreis.
// ---------------------------------------------------------------------------------------------
const TILE_ROOM_PATTERN = /bad|wc|toilette|dusche|k[üu]che/i;
const TILE_MAX_RADIUS_M = 3.4;
const TILE_SIZE_M = 0.6;
const TILE_CANVAS_W = 512;
const TILE_CANVAS_H = 444; // 6 * Hexagon-Radius bei 4 Hexagonen Breite

let modelData = null; // { floorGeometry, grid }
let floorGroup = null;
let floorSignature = null;
let floorMaterials = null;

function makeTileTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = TILE_CANVAS_W;
  canvas.height = TILE_CANVAS_H;
  const ctx = canvas.getContext("2d");
  const R = TILE_CANVAS_W / (4 * Math.sqrt(3));
  const dx = Math.sqrt(3) * R;
  ctx.fillStyle = "#8a9299"; // Fuge
  ctx.fillRect(0, 0, TILE_CANVAS_W, TILE_CANVAS_H);
  for (let row = -1; row <= 5; row++) {
    for (let col = -1; col <= 5; col++) {
      const cx = col * dx + (row % 2 === 0 ? 0 : dx / 2);
      const cy = row * 1.5 * R;
      const tone = 0.93 + hash01(col + 7, row + 3) * 0.12;
      const v = Math.round(206 * tone);
      ctx.fillStyle = `rgb(${v},${v + 3},${v + 6})`;
      ctx.beginPath();
      for (let k = 0; k < 6; k++) {
        const ang = Math.PI / 6 + (k * Math.PI) / 3;
        const px = cx + (R - 3) * Math.cos(ang);
        const py = cy + (R - 3) * Math.sin(ang);
        if (k === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function getFloorMaterials() {
  if (floorMaterials) return floorMaterials;
  const common = { metalness: 0, side: THREE.DoubleSide, clippingPlanes: [clipPlane] };
  floorMaterials = {
    wood: new THREE.MeshStandardMaterial({ map: makeFloorTexture(), roughness: 0.62, ...common }),
    tile: new THREE.MeshStandardMaterial({ map: makeTileTexture(), roughness: 0.35, ...common }),
  };
  return floorMaterials;
}

const NEIGHBOURS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];

// Ordnet jede Rasterzelle dem nächsten benannten Raum zu (-1 = keinem)
function labelRoomCells(grid, roomList) {
  const { wallZone, minX, minZ, gw, gh } = grid;
  const label = new Int16Array(gw * gh).fill(-1);
  const dist = new Float32Array(gw * gh).fill(Infinity);
  const queue = [];
  const limit = roomList.map((r) => (TILE_ROOM_PATTERN.test(r.name) ? TILE_MAX_RADIUS_M / GRID_CELL : Infinity));

  roomList.forEach((room, i) => {
    if (!norm(room.name)) return;
    let cx = Math.floor((room.x - minX) / GRID_CELL);
    let cz = Math.floor((room.z - minZ) / GRID_CELL);
    if (cx < 0 || cz < 0 || cx >= gw || cz >= gh) return;
    // liegt das Schild auf einer Wand, die nächste freie Zelle suchen
    if (wallZone[cz * gw + cx]) {
      let best = null;
      for (let r = 1; r < 14 && !best; r++) {
        for (let dz = -r; dz <= r; dz++) {
          for (let dx = -r; dx <= r; dx++) {
            const x = cx + dx;
            const z = cz + dz;
            if (x >= 0 && z >= 0 && x < gw && z < gh && !wallZone[z * gw + x] && !best) best = [x, z];
          }
        }
      }
      if (!best) return;
      [cx, cz] = best;
    }
    const idx = cz * gw + cx;
    if (label[idx] === -1) {
      label[idx] = i;
      dist[idx] = 0;
      queue.push(idx);
    }
  });

  // gleichzeitige Breitensuche von allen Schildern aus, Wände sperren den Weg
  for (let head = 0; head < queue.length; head++) {
    const idx = queue[head];
    const x = idx % gw;
    const z = (idx - x) / gw;
    const owner = label[idx];
    for (const [dx, dz] of NEIGHBOURS) {
      const nx = x + dx;
      const nz = z + dz;
      if (nx < 0 || nz < 0 || nx >= gw || nz >= gh) continue;
      const nIdx = nz * gw + nx;
      if (label[nIdx] !== -1 || wallZone[nIdx]) continue;
      if (dist[idx] + 1 > limit[owner]) continue;
      label[nIdx] = owner;
      dist[nIdx] = dist[idx] + 1;
      queue.push(nIdx);
    }
  }
  // Zellen unter den Wänden übernehmen den Raum der nächsten beschrifteten Zelle
  const wallQueue = [];
  for (let i = 0; i < label.length; i++) if (label[i] !== -1) wallQueue.push(i);
  for (let head = 0; head < wallQueue.length; head++) {
    const idx = wallQueue[head];
    const x = idx % gw;
    const z = (idx - x) / gw;
    for (const [dx, dz] of NEIGHBOURS) {
      const nx = x + dx;
      const nz = z + dz;
      if (nx < 0 || nz < 0 || nx >= gw || nz >= gh) continue;
      const nIdx = nz * gw + nx;
      if (label[nIdx] !== -1 || !wallZone[nIdx]) continue;
      label[nIdx] = label[idx];
      wallQueue.push(nIdx);
    }
  }
  return label;
}

function applyFloorTypes() {
  if (!modelData || !scene) return;
  const signature = JSON.stringify(rooms.map((r) => [r.x, r.z, norm(r.name)]));
  if (signature === floorSignature) return;
  floorSignature = signature;

  const { floorGeometry, grid } = modelData;
  const label = labelRoomCells(grid, rooms);
  const pos = floorGeometry.getAttribute("position");
  const triCount = pos.count / 3;
  const woodTris = [];
  const tileTris = [];
  for (let t = 0; t < triCount; t++) {
    const cx = (pos.getX(t * 3) + pos.getX(t * 3 + 1) + pos.getX(t * 3 + 2)) / 3;
    const cz = (pos.getZ(t * 3) + pos.getZ(t * 3 + 1) + pos.getZ(t * 3 + 2)) / 3;
    const gx = Math.max(0, Math.min(grid.gw - 1, Math.floor((cx - grid.minX) / GRID_CELL)));
    const gz = Math.max(0, Math.min(grid.gh - 1, Math.floor((cz - grid.minZ) / GRID_CELL)));
    const owner = label[gz * grid.gw + gx];
    (owner >= 0 && TILE_ROOM_PATTERN.test(rooms[owner].name) ? tileTris : woodTris).push(t);
  }

  if (!floorGroup) {
    floorGroup = new THREE.Group();
    scene.add(floorGroup);
  }
  for (const child of floorGroup.children) child.geometry.dispose();
  floorGroup.clear();
  const mats = getFloorMaterials();
  const addFloor = (tris, material, uvScale) => {
    if (!tris.length) return;
    const geo = subsetGeometry(floorGeometry, tris);
    const p = geo.getAttribute("position");
    const uv = new Float32Array(p.count * 2);
    for (let i = 0; i < p.count; i++) {
      uv[i * 2] = p.getX(i) / uvScale[0];
      uv[i * 2 + 1] = p.getZ(i) / uvScale[1];
    }
    geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    const mesh = new THREE.Mesh(geo, material);
    mesh.receiveShadow = true;
    mesh.renderOrder = 5;
    floorGroup.add(mesh);
  };
  addFloor(woodTris, mats.wood, [FLOOR_TILE_M, FLOOR_TILE_M]);
  addFloor(tileTris, mats.tile, [TILE_SIZE_M, (TILE_SIZE_M * TILE_CANVAS_H) / TILE_CANVAS_W]);
  requestRender();
}

// Teppich-Muster (Bordüre + Mittelfeld) in wenigen Farbvarianten
const RUG_PALETTES = [
  ["#8c3b36", "#d9c4a0", "#3b2a2a"],
  ["#4d6a86", "#e8dcc6", "#2a3948"],
  ["#7a8a6a", "#e9e0cc", "#3d4634"],
  ["#b98a63", "#f0e6d4", "#5a4030"],
];
const rugTextures = new Map();

function getRugTexture(index) {
  if (rugTextures.has(index)) return rugTextures.get(index);
  const [main, light, dark] = RUG_PALETTES[index];
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = light;
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = main;
  ctx.fillRect(10, 10, 236, 236);
  ctx.strokeStyle = dark;
  ctx.lineWidth = 5;
  ctx.strokeRect(22, 22, 212, 212);
  ctx.fillStyle = light;
  ctx.globalAlpha = 0.9;
  ctx.fillRect(40, 40, 176, 176);
  ctx.globalAlpha = 1;
  ctx.fillStyle = main;
  ctx.beginPath();
  ctx.moveTo(128, 52);
  ctx.lineTo(204, 128);
  ctx.lineTo(128, 204);
  ctx.lineTo(52, 128);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = dark;
  ctx.beginPath();
  ctx.moveTo(128, 90);
  ctx.lineTo(166, 128);
  ctx.lineTo(128, 166);
  ctx.lineTo(90, 128);
  ctx.closePath();
  ctx.fill();
  // Fransen
  ctx.fillStyle = light;
  for (let i = 0; i < 256; i += 8) {
    ctx.fillRect(i, 0, 4, 6);
    ctx.fillRect(i, 250, 4, 6);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  rugTextures.set(index, texture);
  return texture;
}

function addRugs(rugs) {
  const margin = 0.3;
  for (const rug of rugs) {
    const w = rug.box.max.x - rug.box.min.x + margin * 2;
    const d = rug.box.max.z - rug.box.min.z + margin * 2;
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(w, d),
      new THREE.MeshStandardMaterial({
        map: getRugTexture(Math.floor(rug.seed * RUG_PALETTES.length) % RUG_PALETTES.length),
        roughness: 1,
        metalness: 0,
        clippingPlanes: [clipPlane],
      })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set((rug.box.min.x + rug.box.max.x) / 2, 0.122, (rug.box.min.z + rug.box.max.z) / 2);
    mesh.receiveShadow = true;
    mesh.renderOrder = 5;
    scene.add(mesh);
  }
}

// Blaue Außenfläche (Grundstück/Terrasse) rund um die Wohnung, wie auf den Home-Assistant-Plänen
function makeGroundTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#2f5f86";
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 2600; i++) {
    const tone = 40 + Math.floor(hash01(i, 1.7) * 60);
    ctx.fillStyle = `rgba(${tone},${tone + 40},${tone + 90},0.22)`;
    ctx.fillRect(hash01(i, 2.9) * 256, hash01(i, 5.3) * 256, 2, 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(10, 10);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

// Holzdielen als Textur (Eiche, versetzte Stöße, leichte Maserung) - einmal erzeugt, überall wiederholt.
function makeFloorTexture() {
  const size = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const rows = 8; // Dielenreihen je Kachel (1,2 m -> 15 cm breite Dielen)
  const rowH = size / rows;
  for (let r = 0; r < rows; r++) {
    let x = -hash01(r, 3.3) * size * 0.5;
    while (x < size) {
      const len = size * (0.38 + hash01(r, x) * 0.32);
      const tone = 0.9 + hash01(r * 13.1, x * 0.01) * 0.2;
      const base = [214, 172, 120].map((v) => Math.round(Math.min(255, v * tone)));
      ctx.fillStyle = `rgb(${base[0]},${base[1]},${base[2]})`;
      ctx.fillRect(x, r * rowH, len, rowH);
      // Maserung
      ctx.globalAlpha = 0.1;
      ctx.strokeStyle = "#7a5632";
      for (let g = 0; g < 7; g++) {
        const gy = r * rowH + 6 + hash01(g, r + x) * (rowH - 12);
        ctx.beginPath();
        ctx.moveTo(x + 4, gy);
        ctx.bezierCurveTo(x + len * 0.3, gy + (hash01(g, 1 + x) - 0.5) * 8, x + len * 0.6, gy + (hash01(g, 2 + x) - 0.5) * 8, x + len - 4, gy);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // Fugen
      ctx.fillStyle = "rgba(70,45,25,0.55)";
      ctx.fillRect(x, r * rowH, 2, rowH);
      ctx.fillRect(x, r * rowH, len, 2);
      x += len;
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
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

      const { floorGeometry, restGeometry, rugs, grid } = buildModelGeometries(geometry, size.y);
      addRugs(rugs);

      // Boden: Holzdielen, in Küche und Bad Fliesen (siehe applyFloorTypes)
      modelData = { floorGeometry, grid };
      floorSignature = null;
      applyFloorTypes();

      // Wände und Möbel (Vertexfarben)
      const mesh = new THREE.Mesh(
        restGeometry,
        new THREE.MeshStandardMaterial({
          vertexColors: true,
          roughness: 0.82,
          metalness: 0.0,
          side: THREE.DoubleSide,
          clippingPlanes: [clipPlane],
          clipShadows: true,
        })
      );
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.renderOrder = 6;
      scene.add(mesh);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(restGeometry, 35),
        new THREE.LineBasicMaterial({
          color: COLORS.edge,
          transparent: true,
          opacity: 0.22,
          clippingPlanes: [clipPlane],
        })
      );
      edges.renderOrder = 7;
      scene.add(edges);

      // Außenfläche rund um die Wohnung (nimmt auch den Schatten auf)
      const slab = new THREE.Mesh(
        new THREE.PlaneGeometry(size.x + 4.4, size.z + 4.4),
        new THREE.MeshStandardMaterial({ map: makeGroundTexture(), roughness: 1, metalness: 0 })
      );
      slab.rotation.x = -Math.PI / 2;
      slab.position.y = -0.02;
      slab.receiveShadow = true;
      scene.add(slab);

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
      resetCut();

      setView("top");
      toolbar.classList.remove("hidden");
      setHint(null);

      // Zugriff für spätere Erweiterungen (Marker für Lampen/Steckdosen/Temperatur) und zum Testen.
      window.floorplan = { THREE, renderer, scene, camera, controls, bounds, requestRender, floorPointFromClient };
    },
    undefined,
    () => {
      setHint(
        "Kein 3D-Modell gefunden. Lege eine STL-Datei unter static/models/wohnung.stl ab, sobald sie bereitsteht."
      );
    }
  );
}

function resetCut() {
  const height = Math.min(DEFAULT_CUT_M, bounds.height);
  cutSlider.value = String(height);
  applyCut(height);
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
  // Draufsicht mit engem Blickwinkel (fast orthogonal wie ein gerenderter Plan): die Wände zeigen
  // dann kaum Innenflächen und man sieht in alle Räume.
  camera.fov = kind === "top" ? 20 : 38;
  camera.updateProjectionMatrix();
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
  if (tickOpenings(performance.now())) needsRender = true; // Tür/Fenster in Bewegung
  if (moved || needsRender) {
    renderer.render(scene, camera);
    needsRender = false;
    updateLabelPositions();
  }
}

// ---------------------------------------------------------------------------------------------
// Räume mit Ally-Temperaturen
//
// Die Räume (Position in Metern + Name) liegen auf dem Server (/api/floorplan/rooms), damit alle
// Geräte dieselben Namen sehen. Die Temperaturen kommen von /api/heating/status (der Server
// cached die Danfoss-Cloud-Abfrage 60 s, daher reicht eine Abfrage pro Minute). Ein Thermostat
// gehört zu dem Raum, dessen Name mit seinem Namen übereinstimmt; hat ein Raum mehrere
// Thermostate (z.B. zwei im Arbeitszimmer), werden alle Temperaturen angezeigt.
// ---------------------------------------------------------------------------------------------
const labelLayer = document.getElementById("fpLabels");
const editHint = document.getElementById("fpEditHint");
const roomsButton = document.getElementById("fpRooms");
const openingsButton = document.getElementById("fpOpenings");
const LABEL_HEIGHT_M = 0.15;
const TEMP_POLL_MS = 60000;

let rooms = []; // [{ x, z, name }]
let thermostats = [];
let thermostatRooms = {}; // { thermostatId: Raumname }
let labelEls = [];
let editing = false;
let openingEditing = false;
let tempTimer = null;
let openingTimer = null;

const norm = (s) => String(s || "").trim().toLowerCase();

function thermostatsFor(room) {
  const name = norm(room.name);
  if (!name) return [];
  return thermostats.filter((t) => {
    // Eine feste Zuordnung (Thermostat-ID -> Raum) hat Vorrang vor dem Namen aus der Cloud.
    const tn = norm(thermostatRooms[t.id] || t.name);
    return tn && (tn === name || tn.includes(name) || name.includes(tn));
  });
}

function tempColor(c) {
  if (c < 18) return "#5ec8ff";
  if (c < 20.5) return "#3fe0d0";
  if (c < 23) return "#39ff9d";
  if (c < 25) return "#ffb04a";
  return "#ff6b5e";
}

const fmt = (v) => v.toFixed(1).replace(".", ",");

const THERMOMETER_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/></svg>';

function renderLabels() {
  labelLayer.replaceChildren();
  labelEls = rooms.map((room, index) => {
    const el = document.createElement("div");
    const ts = thermostatsFor(room);
    const named = norm(room.name) !== "";
    el.className = "fp-room" + (named ? "" : " unnamed") + (editing ? " editing" : "");

    const live = ts.filter((t) => typeof t.room_temp === "number");
    if (live.length) {
      el.style.setProperty("--temp", tempColor(live.reduce((s, t) => s + t.room_temp, 0) / live.length));
      const icon = document.createElement("div");
      icon.className = "fp-room-icon";
      icon.innerHTML = THERMOMETER_SVG;
      el.appendChild(icon);
    }

    // Runder Wert (wie die Symbolfelder in den Home-Assistant-Plänen): Zahl im Kreis, Einheit als Etikett
    if (live.length || (named && ts.length) || !named) {
      const circle = document.createElement("div");
      circle.className = "fp-room-circle" + (live.length > 1 ? " multi" : "");
      const value = document.createElement("span");
      value.className = "fp-room-value";
      if (live.length) value.textContent = live.map((t) => fmt(t.room_temp)).join(" / ");
      else if (named) {
        value.textContent = "offline";
        el.classList.add("offline");
      } else value.textContent = String(index + 1);
      circle.appendChild(value);
      if (live.length) {
        const unit = document.createElement("span");
        unit.className = "fp-room-unit";
        unit.textContent = "°C";
        circle.appendChild(unit);
      }
      el.appendChild(circle);
    }

    const name = document.createElement("div");
    name.className = "fp-room-name";
    name.textContent = named ? room.name : `Raum ${index + 1}`;
    el.appendChild(name);

    const sets = ts.filter((t) => typeof t.setpoint === "number");
    if (live.length && sets.length) {
      const set = document.createElement("div");
      set.className = "fp-room-set";
      set.textContent = "Soll " + sets.map((t) => fmt(t.setpoint)).join(" / ");
      el.appendChild(set);
    }

    el.addEventListener("click", () => editRoom(index));
    labelLayer.appendChild(el);
    return el;
  });
  updateLabelPositions();
  renderGlows();
  applyFloorTypes();
}

const projected = new THREE.Vector3();
function placeOverlay(el, x, y, z, w, h) {
  projected.set(x, y, z).project(camera);
  el.style.display = projected.z < 1 ? "" : "none";
  el.style.left = `${(projected.x * 0.5 + 0.5) * w}px`;
  el.style.top = `${(-projected.y * 0.5 + 0.5) * h}px`;
}

function updateLabelPositions() {
  if (!camera) return;
  const w = container.clientWidth;
  const h = container.clientHeight;
  labelEls.forEach((el, i) => placeOverlay(el, rooms[i].x, LABEL_HEIGHT_M, rooms[i].z, w, h));
  const cutY = clipPlane ? clipPlane.constant : 10;
  badgeEls.forEach((el, i) => {
    const o = openings[i];
    if (o) placeOverlay(el, o.x, Math.min(o.head || 2, cutY) + 0.14, o.z, w, h);
  });
}

// Wärmeschein auf dem Boden unter jedem Raumschild (blau = kalt, grün = angenehm, orange/rot = warm),
// wie das Leuchten der Lampen in den Home-Assistant-Grundrissen.
let glowGroup = null;
let glowTexture = null;

function getGlowTexture() {
  if (glowTexture) return glowTexture;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  gradient.addColorStop(0, "rgba(255,255,255,0.95)");
  gradient.addColorStop(0.45, "rgba(255,255,255,0.45)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 256, 256);
  glowTexture = new THREE.CanvasTexture(canvas);
  glowTexture.colorSpace = THREE.SRGBColorSpace;
  return glowTexture;
}

function renderGlows() {
  if (!scene) return;
  if (!glowGroup) {
    glowGroup = new THREE.Group();
    scene.add(glowGroup);
  }
  for (const child of glowGroup.children) {
    child.geometry.dispose();
    child.material.dispose();
  }
  glowGroup.clear();
  for (const room of rooms) {
    const live = thermostatsFor(room).filter((t) => typeof t.room_temp === "number");
    if (!live.length) continue;
    const avg = live.reduce((s, t) => s + t.room_temp, 0) / live.length;
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(3, 3),
      new THREE.MeshBasicMaterial({
        map: getGlowTexture(),
        color: tempColor(avg),
        transparent: true,
        opacity: 0.62,
        depthWrite: false,
        toneMapped: false,
      })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(room.x, 0.13, room.z);
    mesh.renderOrder = 6;
    glowGroup.add(mesh);
  }
  requestRender();
}

// Runde Status-Symbole über Türen/Fenstern (nur sichtbar offen = orange, zu = kleiner grüner Punkt),
// damit man den Zustand auch bei ganzen Wänden in der 3D-Ansicht sieht.
const badgeLayer = document.createElement("div");
badgeLayer.className = "fp-labels fp-badges";
container.appendChild(badgeLayer);
let badgeEls = [];
let badgeSignature = "";

function renderBadges() {
  const signature = openings.map((o) => `${o.id}${o.open ? 1 : 0}`).join();
  if (signature === badgeSignature) return;
  badgeSignature = signature;
  badgeLayer.replaceChildren();
  badgeEls = openings.map((o) => {
    const el = document.createElement("div");
    el.className = `fp-badge ${o.open ? "open" : "closed"}`;
    el.textContent = o.open ? (o.kind === "door" ? "🚪" : "🪟") : "";
    el.title = `${o.name || (o.kind === "door" ? "Tür" : "Fenster")}: ${o.open ? "offen" : "zu"}`;
    badgeLayer.appendChild(el);
    return el;
  });
  updateLabelPositions();
}

async function loadRooms() {
  try {
    const res = await fetch("/api/floorplan/rooms", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      rooms = data.rooms || [];
      thermostatRooms = data.thermostat_rooms || {};
    }
  } catch {
    /* offline: vorhandene Schilder behalten */
  }
  renderLabels();
}

async function saveRooms() {
  try {
    await fetch("/api/floorplan/rooms", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms }),
    });
  } catch {
    window.alert("Speichern fehlgeschlagen - Server nicht erreichbar.");
  }
}

async function pollTemperatures() {
  try {
    const res = await fetch("/api/heating/status", { cache: "no-store" });
    if (res.ok) thermostats = (await res.json()).thermostats || [];
  } catch {
    /* alte Werte behalten */
  }
  renderLabels();
}

function editRoom(index) {
  if (!editing) return;
  const answer = window.prompt("Name des Raums (leer lassen = Schild löschen):", rooms[index].name || "");
  if (answer === null) return;
  if (answer.trim() === "") rooms.splice(index, 1);
  else rooms[index].name = answer.trim();
  renderLabels();
  saveRooms();
}

const ROOM_HINT = "Räume: auf den Boden tippen = neues Schild setzen · auf ein Schild tippen = umbenennen (leer = löschen)";
const OPENING_HINT =
  "Türen/Fenster: auf den Boden tippen = neue Tür/neues Fenster setzen · auf eine Tür/ein Fenster tippen = ändern";

function updateEditHint() {
  editHint.textContent = openingEditing ? OPENING_HINT : ROOM_HINT;
  editHint.classList.toggle("hidden", !(editing || openingEditing));
}

function setEditing(on) {
  editing = on;
  if (on) openingEditing = false;
  roomsButton.classList.toggle("active", on);
  openingsButton.classList.toggle("active", openingEditing);
  updateEditHint();
  renderLabels();
}

function setOpeningEditing(on) {
  openingEditing = on;
  if (on) editing = false;
  openingsButton.classList.toggle("active", on);
  roomsButton.classList.toggle("active", editing);
  updateEditHint();
  renderLabels();
}

// Klick (kein Ziehen) auf den Boden im Bearbeiten-Modus setzt einen neuen Raum.
const floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -LABEL_HEIGHT_M);
const raycaster = new THREE.Raycaster();
let downAt = null;

function floorPointFromClient(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = new THREE.Vector3();
  return raycaster.ray.intersectPlane(floorPlane, hit) ? hit : null;
}

function setupRoomEditing() {
  const canvas = renderer.domElement;
  canvas.addEventListener("pointerdown", (e) => {
    downAt = { x: e.clientX, y: e.clientY };
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
    downAt = null;
    if (moved > 6) return; // war Ziehen/Drehen der Ansicht, kein Antippen

    if (editing) {
      const p = floorPointFromClient(e.clientX, e.clientY);
      if (!p) return;
      const name = window.prompt("Name des neuen Raums:", "");
      if (name === null) return;
      rooms.push({ x: p.x, z: p.z, name: name.trim() });
      renderLabels();
      saveRooms();
    } else {
      handleOpeningTap(e);
    }
  });
}

// Größe der Temperaturschilder: pro Gerät einstellbar (Tablet und PC brauchen unterschiedliche Größen).
const labelScaleSlider = document.getElementById("fpLabelScale");
const labelScaleValue = document.getElementById("fpLabelScaleValue");
const LABEL_SCALE_KEY = "fp.labelScale";

function applyLabelScale(scale) {
  const s = Math.min(1.8, Math.max(0.6, scale || 1));
  labelLayer.style.setProperty("--fp-scale", String(s));
  labelScaleSlider.value = String(s);
  labelScaleValue.textContent = `${Math.round(s * 100)} %`;
  return s;
}

try {
  applyLabelScale(parseFloat(localStorage.getItem(LABEL_SCALE_KEY)));
} catch {
  applyLabelScale(1);
}
labelScaleSlider.addEventListener("input", () => {
  const s = applyLabelScale(parseFloat(labelScaleSlider.value));
  try {
    localStorage.setItem(LABEL_SCALE_KEY, String(s));
  } catch {
    /* ohne Speicher gilt die Einstellung nur bis zum Neuladen */
  }
});

// Zahnrad: Einstellungsfenster ein-/ausblenden (Zustand pro Gerät gemerkt, Standard: ausgeblendet).
const gearButton = document.getElementById("fpGear");
const PANEL_KEY = "fp.panelOpen";

function setPanelOpen(open, remember = true) {
  toolbar.classList.toggle("collapsed", !open);
  gearButton.setAttribute("aria-expanded", String(open));
  if (!remember) return;
  try {
    localStorage.setItem(PANEL_KEY, open ? "1" : "0");
  } catch {
    /* ohne Speicher gilt es nur bis zum Neuladen */
  }
}

try {
  setPanelOpen(localStorage.getItem(PANEL_KEY) === "1", false);
} catch {
  setPanelOpen(false, false);
}
gearButton.addEventListener("click", () => setPanelOpen(toolbar.classList.contains("collapsed")));

roomsButton.addEventListener("click", () => setEditing(!editing));
openingsButton.addEventListener("click", () => setOpeningEditing(!openingEditing));

// ---------------------------------------------------------------------------------------------
// Türen und Fenster (beweglich)
//
// Layout (Position, Maße, Anschlag) und Zustand (offen/zu) liegen getrennt auf dem Server
// (/api/floorplan/openings). Antippen schaltet den Zustand um; später setzen Tür-/Fensterkontakte
// ihn über PUT /api/floorplan/openings/<id>/state. Der Grundriss holt den Zustand alle 5 s.
// Ein leuchtender Streifen in der Öffnung zeigt den Zustand auch in der Draufsicht:
// grün = zu, orange = offen.
// ---------------------------------------------------------------------------------------------
const OPENING_POLL_MS = 5000;
const FLOOR_TOP_M = 0.1;
const OPEN_SECONDS = 0.35;
const OPEN_ANGLE = { door: THREE.MathUtils.degToRad(85), window: THREE.MathUtils.degToRad(70) };
const CLOSED_COLOR = 0x39ff9d;
const OPEN_COLOR = 0xffa23a;

let openings = []; // Layout + open-Flag vom Server
let layoutSignature = "";
let openingGroup = null;
let openingObjs = new Map(); // id -> { group, pivots:[{pivot, sign}], strip, progress, target }
let openingMaterials = null;
let lastTick = 0;

function getOpeningMaterials() {
  if (openingMaterials) return openingMaterials;
  const clip = { clippingPlanes: [clipPlane], clipShadows: true };
  openingMaterials = {
    door: new THREE.MeshStandardMaterial({ color: 0xe6d3b3, roughness: 0.55, metalness: 0, ...clip }),
    frame: new THREE.MeshStandardMaterial({ color: 0xfafbfc, roughness: 0.5, metalness: 0, ...clip }),
    glass: new THREE.MeshStandardMaterial({
      color: 0x9ed3ff,
      roughness: 0.1,
      metalness: 0,
      transparent: true,
      opacity: 0.32,
      side: THREE.DoubleSide,
      depthWrite: false,
      clippingPlanes: [clipPlane],
    }),
    closed: new THREE.MeshBasicMaterial({ color: CLOSED_COLOR, clippingPlanes: [clipPlane] }),
    open: new THREE.MeshBasicMaterial({ color: OPEN_COLOR, clippingPlanes: [clipPlane] }),
  };
  return openingMaterials;
}

function box(w, h, d, material, shadow = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.castShadow = shadow;
  mesh.receiveShadow = true;
  return mesh;
}

// Ein Flügel: Drehpunkt (pivot) an der Bandseite, der Flügel ragt zur Öffnungsmitte.
function buildLeaf(o, mats, side, leafWidth) {
  const isDoor = o.kind === "door";
  const y0 = isDoor ? FLOOR_TOP_M : o.sill + 0.02;
  const top = isDoor ? Math.min(o.head, 2.1) - 0.02 : o.head - 0.02;
  const h = Math.max(0.2, top - y0);

  const pivot = new THREE.Group();
  pivot.position.set((side * o.width) / 2, y0, 0);

  const leaf = new THREE.Group();
  leaf.position.set((-side * leafWidth) / 2, h / 2, 0);
  if (isDoor) {
    leaf.add(box(leafWidth - 0.03, h, 0.04, mats.door));
    const handle = box(0.12, 0.025, 0.07, mats.frame, false);
    handle.position.set(-side * (leafWidth / 2 - 0.12), -0.05, 0);
    leaf.add(handle);
  } else {
    const bar = 0.05;
    leaf.add(box(leafWidth - 0.04, h - 0.04, 0.012, mats.glass, false));
    const top = box(leafWidth, bar, 0.05, mats.frame);
    top.position.y = h / 2 - bar / 2;
    const bottom = box(leafWidth, bar, 0.05, mats.frame);
    bottom.position.y = -h / 2 + bar / 2;
    const left = box(bar, h, 0.05, mats.frame);
    left.position.x = -leafWidth / 2 + bar / 2;
    const right = box(bar, h, 0.05, mats.frame);
    right.position.x = leafWidth / 2 - bar / 2;
    leaf.add(top, bottom, left, right);
  }
  pivot.add(leaf);
  return { pivot, sign: side };
}

function buildOpening(o) {
  const mats = getOpeningMaterials();
  const group = new THREE.Group();
  group.position.set(o.x, 0, o.z);
  group.rotation.y = o.along ? -Math.PI / 2 : 0; // lokale x-Achse läuft entlang der Wand
  group.userData.openingId = o.id;

  const pivots = [];
  if (o.kind === "window" && o.width > 1.2) {
    // breites Fenster: zwei Flügel, an beiden Seiten angeschlagen
    for (const side of [-1, 1]) pivots.push(buildLeaf(o, mats, side, o.width / 2));
  } else {
    pivots.push(buildLeaf(o, mats, o.hinge || 1, o.width));
  }
  pivots.forEach((p) => group.add(p.pivot));

  const stripY = (o.kind === "door" ? FLOOR_TOP_M : o.sill) + 0.012;
  const strip = new THREE.Mesh(
    new THREE.BoxGeometry(o.width, 0.024, Math.min(0.2, Math.max(0.08, o.thick * 0.8))),
    mats.closed
  );
  strip.position.set(0, stripY, 0);
  group.add(strip);

  return { group, pivots, strip, progress: o.open ? 1 : 0, target: o.open ? 1 : 0, data: o };
}

function applyPose(obj) {
  const o = obj.data;
  const angle = OPEN_ANGLE[o.kind] * obj.progress;
  obj.pivots.forEach(({ pivot, sign }) => {
    pivot.rotation.y = (o.swing || 1) * sign * angle;
  });
  const mats = getOpeningMaterials();
  obj.strip.material = obj.target > 0.5 ? mats.open : mats.closed;
}

function buildAllOpenings() {
  if (!scene) return;
  if (!openingGroup) {
    openingGroup = new THREE.Group();
    scene.add(openingGroup);
  }
  openingGroup.clear();
  openingObjs = new Map();
  for (const o of openings) {
    const obj = buildOpening(o);
    applyPose(obj);
    openingGroup.add(obj.group);
    openingObjs.set(o.id, obj);
  }
  requestRender();
}

// Gleitet Türen/Fenster zum Soll-Zustand. Liefert true, solange noch etwas in Bewegung ist.
function tickOpenings(now) {
  const dt = Math.min(0.1, (now - lastTick) / 1000 || 0);
  lastTick = now;
  let moving = false;
  for (const obj of openingObjs.values()) {
    if (obj.progress === obj.target) continue;
    const step = dt / OPEN_SECONDS;
    obj.progress =
      obj.progress < obj.target ? Math.min(obj.target, obj.progress + step) : Math.max(obj.target, obj.progress - step);
    applyPose(obj);
    if (obj.progress !== obj.target) moving = true;
  }
  return moving;
}

function signatureOf(list) {
  return JSON.stringify(list.map(({ open, changed_at, ...layout }) => layout));
}

function applyOpeningData(list) {
  const signature = signatureOf(list);
  openings = list;
  if (signature !== layoutSignature) {
    layoutSignature = signature;
    badgeSignature = "";
    buildAllOpenings();
    renderBadges();
    return;
  }
  renderBadges();
  for (const o of list) {
    const obj = openingObjs.get(o.id);
    if (!obj) continue;
    obj.data = o;
    const target = o.open ? 1 : 0;
    if (obj.target !== target) {
      obj.target = target;
      applyPose(obj);
      requestRender();
    }
  }
}

async function loadOpenings() {
  try {
    const res = await fetch("/api/floorplan/openings", { cache: "no-store" });
    if (res.ok) applyOpeningData((await res.json()).openings || []);
  } catch {
    /* offline: alten Zustand behalten */
  }
}

async function saveOpenings() {
  try {
    const layout = openings.map(({ open, changed_at, ...rest }) => rest);
    await fetch("/api/floorplan/openings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ openings: layout }),
    });
  } catch {
    window.alert("Speichern fehlgeschlagen - Server nicht erreichbar.");
  }
}

async function sendOpeningState(id, isOpen) {
  try {
    await fetch(`/api/floorplan/openings/${encodeURIComponent(id)}/state`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ open: isOpen }),
    });
  } catch {
    /* der nächste Abruf holt den echten Zustand zurück */
  }
}

function openingFromEvent(e) {
  if (!openingGroup || !openingGroup.children.length) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects(openingGroup.children, true);
  for (const hit of hits) {
    let node = hit.object;
    while (node && !node.userData.openingId) node = node.parent;
    if (node) return openings.find((o) => o.id === node.userData.openingId) || null;
  }
  return null;
}

function toggleOpening(o) {
  o.open = !o.open;
  const obj = openingObjs.get(o.id);
  if (obj) {
    obj.target = o.open ? 1 : 0;
    applyPose(obj);
  }
  renderBadges();
  requestRender();
  sendOpeningState(o.id, o.open);
}

function openingLabel(o) {
  return o.name || (o.kind === "door" ? "Tür" : "Fenster");
}

function editOpening(o) {
  const answer = window.prompt(
    `${openingLabel(o)} (${o.width.toFixed(2).replace(".", ",")} m breit)\n` +
      "h = Bänder links/rechts tauschen\n" +
      "s = Aufschwingrichtung umdrehen\n" +
      "k = Tür <-> Fenster\n" +
      "b = Breite ändern\n" +
      "n = Namen vergeben\n" +
      "l = löschen",
    ""
  );
  if (answer === null) return;
  const cmd = answer.trim().toLowerCase()[0];
  if (cmd === "h") o.hinge = -(o.hinge || 1);
  else if (cmd === "s") o.swing = -(o.swing || 1);
  else if (cmd === "k") {
    o.kind = o.kind === "door" ? "window" : "door";
    o.sill = o.kind === "window" ? 0.95 : 0;
    o.head = o.kind === "window" ? 2.3 : 2.1;
  } else if (cmd === "b") {
    const w = parseFloat((window.prompt("Neue Breite in Metern:", String(o.width)) || "").replace(",", "."));
    if (!(w > 0.3 && w < 6)) return;
    o.width = w;
  } else if (cmd === "n") {
    const name = window.prompt("Name (z.B. Balkontür Wohnzimmer):", o.name || "");
    if (name === null) return;
    o.name = name.trim().slice(0, 40);
  } else if (cmd === "l") {
    openings = openings.filter((x) => x !== o);
  } else return;
  layoutSignature = ""; // erzwingt Neuaufbau
  applyOpeningData(openings);
  saveOpenings();
}

function newOpening(point) {
  const kindAnswer = (window.prompt("Neue Öffnung: t = Tür, f = Fenster", "t") || "").trim().toLowerCase()[0];
  if (kindAnswer !== "t" && kindAnswer !== "f") return;
  const alongAnswer = (
    window.prompt("Wandrichtung in der Draufsicht: w = waagerecht, s = senkrecht", "w") || ""
  ).trim().toLowerCase()[0];
  if (alongAnswer !== "w" && alongAnswer !== "s") return;
  const kind = kindAnswer === "t" ? "door" : "window";
  const id = `${kind === "door" ? "t" : "f"}${Date.now().toString(36)}`;
  openings.push({
    id,
    kind,
    x: Math.round(point.x * 100) / 100,
    z: Math.round(point.z * 100) / 100,
    width: kind === "door" ? 0.9 : 1.2,
    along: alongAnswer === "s" ? 1 : 0,
    thick: 0.1,
    sill: kind === "window" ? 0.95 : 0,
    head: kind === "window" ? 2.3 : 2.1,
    hinge: 1,
    swing: 1,
    name: "",
    open: false,
  });
  layoutSignature = "";
  applyOpeningData(openings);
  saveOpenings();
}

function handleOpeningTap(e) {
  const hit = openingFromEvent(e);
  if (openingEditing) {
    if (hit) editOpening(hit);
    else {
      const p = floorPointFromClient(e.clientX, e.clientY);
      if (p) newOpening(p);
    }
  } else if (hit) {
    toggleOpening(hit);
  }
}

function startViewer() {
  if (!initialized) {
    initialized = true;
    if (!initScene()) return;
    setupRoomEditing();
  }
  if (!renderer) return;
  loadRooms(); // bei jedem Öffnen neu holen, damit Änderungen von anderen Geräten sichtbar sind
  loadOpenings();
  if (openingTimer === null) openingTimer = setInterval(loadOpenings, OPENING_POLL_MS);
  resize();
  requestRender();
  if (animationId === null) animate();
  if (tempTimer === null) {
    pollTemperatures();
    tempTimer = setInterval(pollTemperatures, TEMP_POLL_MS);
  }
}

function stopViewer() {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }
  if (tempTimer !== null) {
    clearInterval(tempTimer);
    tempTimer = null;
  }
  if (openingTimer !== null) {
    clearInterval(openingTimer);
    openingTimer = null;
  }
}

viewButtons.forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.getElementById("fpReset").addEventListener("click", () => {
  if (!bounds) return;
  resetCut();
  setView("top");
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
