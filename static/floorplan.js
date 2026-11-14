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
      resetCut();

      setView("iso");
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

function renderLabels() {
  labelLayer.replaceChildren();
  labelEls = rooms.map((room, index) => {
    const el = document.createElement("div");
    const ts = thermostatsFor(room);
    const named = norm(room.name) !== "";
    el.className = "fp-room" + (named ? "" : " unnamed") + (editing ? " editing" : "");

    const name = document.createElement("div");
    name.className = "fp-room-name";
    name.textContent = named ? room.name : `Raum ${index + 1}`;
    el.appendChild(name);

    const live = ts.filter((t) => typeof t.room_temp === "number");
    if (live.length) {
      const temp = document.createElement("div");
      temp.className = "fp-room-temp";
      temp.textContent = live.map((t) => fmt(t.room_temp)).join(" / ") + " °C";
      el.style.setProperty("--temp", tempColor(live.reduce((s, t) => s + t.room_temp, 0) / live.length));
      el.appendChild(temp);
      const sets = ts.filter((t) => typeof t.setpoint === "number");
      if (sets.length) {
        const set = document.createElement("div");
        set.className = "fp-room-set";
        set.textContent = "Soll " + sets.map((t) => fmt(t.setpoint)).join(" / ");
        el.appendChild(set);
      }
    } else if (named && ts.length) {
      el.classList.add("offline");
      const temp = document.createElement("div");
      temp.className = "fp-room-temp";
      temp.textContent = "offline";
      el.appendChild(temp);
    }

    el.addEventListener("click", () => editRoom(index));
    labelLayer.appendChild(el);
    return el;
  });
  updateLabelPositions();
}

const projected = new THREE.Vector3();
function updateLabelPositions() {
  if (!camera || !labelEls.length) return;
  const w = container.clientWidth;
  const h = container.clientHeight;
  labelEls.forEach((el, i) => {
    projected.set(rooms[i].x, LABEL_HEIGHT_M, rooms[i].z).project(camera);
    const visible = projected.z < 1;
    el.style.display = visible ? "" : "none";
    el.style.left = `${(projected.x * 0.5 + 0.5) * w}px`;
    el.style.top = `${(-projected.y * 0.5 + 0.5) * h}px`;
  });
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
    buildAllOpenings();
    return;
  }
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
