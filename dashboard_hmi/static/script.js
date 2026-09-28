/* ============================================================
   script.js
   Toda la animacion corre en el navegador: el backend (Flask)
   solo manda una vez la serie completa de presion + el timeline
   de eventos de deteccion/localizacion ya calculado. Aqui se
   "reproduce" esa serie a la velocidad que el usuario eligio,
   como si llegara en vivo de los sensores.
   ============================================================ */

const els = {
  ubicacion: document.getElementById("ubicacion"),
  ubicacionVal: document.getElementById("ubicacion-val"),
  diametro: document.getElementById("diametro"),
  diametroVal: document.getElementById("diametro-val"),
  tInicio: document.getElementById("t_inicio"),
  tInicioVal: document.getElementById("t_inicio-val"),
  semilla: document.getElementById("semilla"),
  duracion: document.getElementById("duracion"),
  duracionVal: document.getElementById("duracion-val"),
  btnIniciar: document.getElementById("btn-iniciar"),
  btnReset: document.getElementById("btn-reset"),
  alarmBanner: document.getElementById("alarm-banner"),
  alarmText: document.getElementById("alarm-text"),
  canvas: document.getElementById("trend-canvas"),
  tagUbicacion: document.getElementById("tag-ubicacion"),
  tagDiametro: document.getElementById("tag-diametro"),
  tagLitros: document.getElementById("tag-litros"),
  tagCosto: document.getElementById("tag-costo"),
  panelProyeccion: document.getElementById("panel-projection"),
  tablaProyeccion: document.querySelector("#tabla-proyeccion tbody"),
  leakMarker: document.getElementById("leak-marker"),
  leakLabelText: document.getElementById("leak-label-text"),
  statusLeft: document.getElementById("status-left"),
};

const ctx = els.canvas.getContext("2d");
const LONGITUD_M = window.LONGITUD_M || 10000;

let animId = null;

// ---------- Sliders: reflejar valor numerico ----------
function bindSlider(input, out, decimals = 0) {
  const actualizar = () => { out.textContent = parseFloat(input.value).toFixed(decimals); };
  input.addEventListener("input", actualizar);
  actualizar();
}
bindSlider(els.ubicacion, els.ubicacionVal, 0);
bindSlider(els.diametro, els.diametroVal, 0);
bindSlider(els.tInicio, els.tInicioVal, 1);
bindSlider(els.duracion, els.duracionVal, 0);

// ---------- Dibujo del canvas (registrador de tendencia) ----------
function dibujarChart(t, presionA, presionB, hastaIndice, eventosDisparados) {
  const W = els.canvas.width;
  const H = els.canvas.height;
  ctx.clearRect(0, 0, W, H);

  const duracion = t.length ? t[t.length - 1] : 30;
  const yMin = 30, yMax = 70; // bar, rango fijo de la pantalla del registrador

  const xOf = (tt) => (tt / duracion) * W;
  const yOf = (p) => H - ((p - yMin) / (yMax - yMin)) * H;

  // Rejilla horizontal (presion)
  ctx.strokeStyle = "#0a3a0a";
  ctx.fillStyle = "#2fae2f";
  ctx.font = "11px 'Share Tech Mono', monospace";
  ctx.lineWidth = 1;
  for (let p = yMin; p <= yMax; p += 10) {
    const y = yOf(p);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
    ctx.fillText(p.toFixed(0), 4, y - 2);
  }
  // Rejilla vertical (tiempo)
  for (let s = 0; s <= duracion; s += 5) {
    const x = xOf(s);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
    ctx.fillText(s.toFixed(0) + "s", x + 3, H - 4);
  }

  // Trazo sensor A (verde) y B (ambar)
  const dibujarTrazo = (serie, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (let i = 0; i <= hastaIndice && i < t.length; i++) {
      const x = xOf(t[i]);
      const y = yOf(serie[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  };
  dibujarTrazo(presionA, "#33ff55");
  dibujarTrazo(presionB, "#ffb000");

  // Marcas verticales rojas donde se disparo un evento
  ctx.strokeStyle = "#ff2b2b";
  ctx.setLineDash([4, 3]);
  eventosDisparados.forEach((ev) => {
    const x = xOf(ev.t);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  });
  ctx.setLineDash([]);
}

// ---------- Alarmas ----------
function setAlarma(estado, texto) {
  els.alarmBanner.dataset.state = estado;
  els.alarmText.textContent = texto;
}

// ---------- Marcador de fuga en el esquema ----------
function mostrarMarcadorFuga(ubicacionM) {
  const frac = Math.min(1, Math.max(0, ubicacionM / LONGITUD_M));
  const x = 60 + frac * (940 - 60);
  els.leakMarker.style.display = "block";
  els.leakMarker.querySelectorAll("line, polygon").forEach((el) => el.setAttribute("transform", `translate(${x - 500}, 0)`));
  els.leakLabelText.setAttribute("transform", `translate(${x - 500}, 0)`);
  els.leakLabelText.textContent = `${ubicacionM.toFixed(0)} m`;
}

function ocultarMarcadorFuga() {
  els.leakMarker.style.display = "none";
}

// ---------- Proyeccion final ----------
function mostrarProyeccion(caudalLpm, costoPorMinuto) {
  const periodos = [
    ["1 HORA", 60],
    ["1 DIA", 60 * 24],
    ["1 SEMANA", 60 * 24 * 7],
  ];
  els.tablaProyeccion.innerHTML = "";
  periodos.forEach(([etiqueta, minutos]) => {
    const litros = caudalLpm * minutos;
    const pesos = costoPorMinuto * minutos;
    const fila = document.createElement("tr");
    fila.innerHTML = `<td>${etiqueta}</td><td>${litros.toLocaleString("es-MX", {maximumFractionDigits: 0})} L</td><td>$${pesos.toLocaleString("es-MX", {maximumFractionDigits: 0})} MXN</td>`;
    els.tablaProyeccion.appendChild(fila);
  });
  els.panelProyeccion.style.display = "block";
}

// ---------- Reset visual ----------
function resetPantalla() {
  if (animId) cancelAnimationFrame(animId);
  animId = null;
  setAlarma("normal", "SISTEMA EN ESPERA — SIN ALARMAS ACTIVAS");
  ocultarMarcadorFuga();
  els.tagUbicacion.textContent = "-----";
  els.tagDiametro.textContent = "-----";
  els.tagLitros.textContent = "-----";
  els.tagCosto.textContent = "-----";
  els.panelProyeccion.style.display = "none";
  ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);
  els.statusLeft.textContent = "LISTO";
}

els.btnReset.addEventListener("click", resetPantalla);

// ---------- Flujo principal ----------
els.btnIniciar.addEventListener("click", async () => {
  resetPantalla();
  els.btnIniciar.disabled = true;
  els.statusLeft.textContent = "SOLICITANDO SIMULACION AL SERVIDOR...";
  setAlarma("normal", "TRANSMITIENDO DATOS DE LOS SENSORES...");

  const payload = {
    ubicacion: parseFloat(els.ubicacion.value),
    diametro_mm: parseFloat(els.diametro.value),
    t_inicio: parseFloat(els.tInicio.value),
    semilla: parseInt(els.semilla.value, 10),
  };

  let data;
  try {
    const resp = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    data = await resp.json();
  } catch (err) {
    setAlarma("alta", "ERROR DE COMUNICACION CON EL SERVIDOR");
    els.statusLeft.textContent = "ERROR: " + err.message;
    els.btnIniciar.disabled = false;
    return;
  }

  const { t, presion_a_bar, presion_b_bar, eventos } = data;
  const n = t.length;
  const duracionVideoS = parseFloat(els.duracion.value);

  let eventoAlta = null;
  const eventosDisparados = [];
  let idxEvento = 0;

  const inicioReal = performance.now();
  els.statusLeft.textContent = "SIMULACION EN CURSO...";

  function frame(ahora) {
    const transcurridoReal = (ahora - inicioReal) / 1000;
    const tSimActual = Math.min(t[n - 1], (transcurridoReal / duracionVideoS) * t[n - 1]);

    let idx = 0;
    while (idx < n - 1 && t[idx] < tSimActual) idx++;

    // Disparar eventos cuyo tiempo ya se alcanzo
    while (idxEvento < eventos.length && eventos[idxEvento].t <= tSimActual) {
      const ev = eventos[idxEvento];
      eventosDisparados.push(ev);
      if (ev.confianza === "alta") {
        eventoAlta = ev;
        setAlarma("alta", `FUGA LOCALIZADA A ${ev.ubicacion_m.toFixed(0)} m DEL SENSOR A — DIAM. EST. ${ev.diametro_mm.toFixed(1)} mm`);
        mostrarMarcadorFuga(ev.ubicacion_m);
        els.tagUbicacion.textContent = ev.ubicacion_m.toFixed(0);
        els.tagDiametro.textContent = ev.diametro_mm.toFixed(1);
      } else if (ev.confianza === "baja") {
        setAlarma("baja", "ALERTA DE BAJA CONFIANZA — SOLO UN SENSOR DETECTO EL EVENTO");
      } else if (ev.confianza === "ninguna") {
        setAlarma("normal", "SIN EVENTOS DETECTADOS");
      }
      idxEvento++;
    }

    // Acumular litros/costo si ya hay confianza alta
    if (eventoAlta) {
      const minutosTranscurridos = Math.max(0, (tSimActual - eventoAlta.t_deteccion) / 60);
      const litros = eventoAlta.caudal_perdido_lpm * minutosTranscurridos;
      const pesos = eventoAlta.costo_por_minuto_mxn * minutosTranscurridos;
      els.tagLitros.textContent = litros.toLocaleString("es-MX", { maximumFractionDigits: 0 });
      els.tagCosto.textContent = pesos.toLocaleString("es-MX", { maximumFractionDigits: 0 });
    }

    dibujarChart(t, presion_a_bar, presion_b_bar, idx, eventosDisparados);

    if (tSimActual < t[n - 1]) {
      animId = requestAnimationFrame(frame);
    } else {
      els.statusLeft.textContent = "SIMULACION TERMINADA";
      els.btnIniciar.disabled = false;
      if (eventoAlta) {
        mostrarProyeccion(eventoAlta.caudal_perdido_lpm, eventoAlta.costo_por_minuto_mxn);
      } else if (eventosDisparados.length === 0 || eventosDisparados[eventosDisparados.length - 1].confianza !== "baja") {
        setAlarma("normal", "SIMULACION TERMINADA — NO SE DISPARO NINGUNA ALERTA");
      }
    }
  }

  animId = requestAnimationFrame(frame);
});
