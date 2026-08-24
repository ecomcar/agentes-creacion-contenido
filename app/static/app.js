// Panel del sistema UGC — vanilla JS, sin dependencias, habla directo con
// la API que ya construimos y probamos (app/api/).

const API = "";  // mismo origen: la API sirve este archivo también

let proyectoActual = null;   // code del proyecto seleccionado
let cacheProyecto = null;    // último detalle recibido del backend

// ---------------------------------------------------------------- fetch

async function api(path, opciones = {}) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opciones,
  });
  const cuerpo = await resp.json().catch(() => null);
  if (!resp.ok) {
    const detalle = cuerpo?.detail || `Error ${resp.status}`;
    throw new Error(typeof detalle === "string" ? detalle : JSON.stringify(detalle));
  }
  return cuerpo;
}

// -------------------------------------------------------------- arranque

async function iniciar() {
  try {
    await api("/health");
    document.getElementById("estado-conexion").textContent = "conectado";
  } catch {
    document.getElementById("estado-conexion").textContent = "sin conexión con el servidor";
  }
  await cargarListaProyectos();

  document.getElementById("form-nuevo-proyecto").addEventListener("submit", async (e) => {
    e.preventDefault();
    const datos = Object.fromEntries(new FormData(e.target));
    try {
      const proyecto = await api("/projects", {
        method: "POST", body: JSON.stringify(datos),
      });
      e.target.reset();
      await cargarListaProyectos();
      seleccionarProyecto(proyecto.code);
    } catch (err) {
      alert("No se pudo crear el proyecto: " + err.message);
    }
  });
}

// --------------------------------------------------------- lista lateral

async function cargarListaProyectos() {
  // No hay endpoint "listar todos" todavía — se muestra el que esté
  // seleccionado y se deja el buscador manual como respaldo simple.
  const ul = document.getElementById("lista-proyectos");
  if (!proyectoActual) {
    ul.innerHTML = `<li class="vacio" style="cursor:default;">
      Escribe el código de un proyecto existente arriba, o crea uno nuevo.
    </li>`;
    return;
  }
}

function seleccionarProyecto(code) {
  proyectoActual = code;
  renderProyectoSeleccionado();
  cargarProyecto();
}

function renderProyectoSeleccionado() {
  const ul = document.getElementById("lista-proyectos");
  if (!proyectoActual) return;
  ul.innerHTML = `<li class="activo">
    <div class="code">${proyectoActual}</div>
    <div class="marca">seleccionado</div>
  </li>`;
}

// --------------------------------------------------------- buscar proyecto

// Barra simple para abrir un proyecto ya existente por código.
(function agregarBuscador() {
  window.addEventListener("DOMContentLoaded", () => {
    const nav = document.querySelector("nav.proyectos");
    const buscador = document.createElement("div");
    buscador.style.marginBottom = "16px";
    buscador.innerHTML = `
      <label>Abrir proyecto existente</label>
      <input id="input-buscar-proyecto" placeholder="ej. UGC-0001">
      <button class="secundario chico" id="btn-buscar-proyecto"
              style="margin-top:6px; width:100%;">Abrir</button>
    `;
    nav.insertBefore(buscador, nav.querySelector("h2").nextSibling);
    document.getElementById("btn-buscar-proyecto").addEventListener("click", () => {
      const code = document.getElementById("input-buscar-proyecto").value.trim();
      if (code) seleccionarProyecto(code);
    });
  });
})();

// ----------------------------------------------------------- carga central

async function cargarProyecto() {
  const contenido = document.getElementById("contenido");
  contenido.innerHTML = `<div class="vacio">Cargando…</div>`;

  try {
    cacheProyecto = await api(`/projects/${proyectoActual}`);
  } catch (err) {
    contenido.innerHTML = `<div class="error-msg">No se encontró el proyecto
      '${proyectoActual}': ${err.message}</div>`;
    return;
  }

  const [clips, artefactos] = await Promise.all([
    api(`/projects/${proyectoActual}/clips`),
    api(`/projects/${proyectoActual}/artifacts`),
  ]);

  render(cacheProyecto, clips, artefactos);
}

// ------------------------------------------------------------- render raíz

const ETAPAS = ["research", "strategy", "hooks", "script", "storyboard",
                "identity", "image", "video", "voice", "edit", "audit", "published"];
const ETAPA_ES = {
  research: "Investigación", strategy: "Estrategia", hooks: "Hooks",
  script: "Guion", storyboard: "Storyboard", identity: "Identidad",
  image: "Imagen", video: "Video", voice: "Voz", edit: "Montaje",
  audit: "Auditoría", published: "Publicado",
};

function render(proyecto, clips, artefactos) {
  const contenido = document.getElementById("contenido");
  const idxActual = ETAPAS.indexOf(proyecto.current_stage);

  contenido.innerHTML = `
    <div class="zona">
      <h2>${proyecto.code} — ${proyecto.brand_name}</h2>
      <div class="pipeline">
        ${ETAPAS.map((e, i) => `
          <span class="etapa ${i === idxActual ? "actual" : i < idxActual ? "hecha" : ""}">
            ${ETAPA_ES[e]}
          </span>`).join("")}
      </div>
      <p class="costo" style="margin-top:12px;">
        Costo acumulado: <b>$${proyecto.total_cost_usd.toFixed(4)}</b>
        · Estado: <span class="badge ${proyecto.stage_status}">${proyecto.stage_status}</span>
      </p>
    </div>

    <div class="zona" id="zona-agente"></div>

    <div class="zona">
      <h2>Clips (${clips.length})</h2>
      ${clips.length === 0
        ? `<div class="vacio">Sin clips todavía — aparecerán al llegar al storyboard.</div>`
        : clips.map(c => `<div style="font-size:13px; padding:6px 0;">
             <b>${c.code}</b> — ${c.role || "—"} — ${c.dialogue || "(sin diálogo)"}
           </div>`).join("")}
    </div>

    <div class="zona">
      <h2>Historial de artefactos</h2>
      ${artefactos.length === 0
        ? `<div class="vacio">Ninguno todavía.</div>`
        : artefactos.map(a => `
            <div style="font-size:13px; padding:6px 0; display:flex; justify-content:space-between;">
              <span>${a.type} v${a.version}</span>
              <span class="badge ${a.status}">${a.status}</span>
            </div>`).join("")}
    </div>

    <div class="zona">
      <h2>Storyboard</h2>
      <p class="proximamente">Próximamente — depende de imagen y video, todavía sin conectar a la API.</p>
    </div>

    <div class="zona">
      <h2>Auditor</h2>
      <p class="proximamente">Próximamente — depende del pipeline de video.</p>
    </div>
  `;

  renderPanelAgente(proyecto, artefactos);
}

// ------------------------------------------------------- panel del agente

function ultimoArtefacto(artefactos, tipo) {
  const filtrados = artefactos.filter(a => a.type === tipo);
  if (filtrados.length === 0) return null;
  return filtrados.reduce((a, b) => (a.version > b.version ? a : b));
}

function renderPanelAgente(proyecto, artefactos) {
  const zona = document.getElementById("zona-agente");
  const etapa = proyecto.current_stage;
  const pendienteAprobacion = proyecto.stage_status === "pending_human_approval";

  if (etapa === "research") {
    zona.innerHTML = `
      <h2>Agente 1 · Investigación</h2>
      <form id="form-research">
        <label>Nombre del producto</label>
        <input name="product_name" required>
        <label>Marca</label>
        <input name="brand_name" required value="${proyecto.brand_name}">
        <label>Descripción</label>
        <textarea name="description" rows="3" required></textarea>
        <label>Audiencia conocida (opcional)</label>
        <input name="known_audience">
        <label>Voz de marca (opcional)</label>
        <input name="brand_voice">
        <div class="fila-botones">
          <button type="submit">Ejecutar investigación</button>
        </div>
      </form>
      <div id="resultado-etapa"></div>
    `;
    document.getElementById("form-research").addEventListener("submit", async (e) => {
      e.preventDefault();
      const datos = Object.fromEntries(new FormData(e.target));
      await correrEtapa("research", datos);
    });
    return;
  }

  if (etapa === "strategy") {
    const brief = ultimoArtefacto(artefactos, "research_brief");
    zona.innerHTML = `
      <h2>Agente 2 · Estrategia</h2>
      ${brief ? `<p class="costo">Basado en el brief aprobado (v${brief.version}).</p>` : ""}
      ${pendienteAprobacion ? "" : `
        <div class="fila-botones">
          <button id="btn-run-strategy">Generar estrategia</button>
        </div>`}
      <div id="resultado-etapa"></div>
    `;
    const boton = document.getElementById("btn-run-strategy");
    if (boton) boton.addEventListener("click", () => correrEtapa("strategy", {}));
    if (pendienteAprobacion) mostrarAngulosParaAprobar(artefactos);
    return;
  }

  if (etapa === "hooks") {
    const strategy = ultimoArtefacto(artefactos, "strategy");
    if (!pendienteAprobacion) {
      const angulos = strategy ? strategy.payload.angles : [];
      zona.innerHTML = `
        <h2>Agente 3 · Hooks</h2>
        <p class="costo">Elige el ángulo sobre el que generar los hooks:</p>
        <div id="lista-angulos">
          ${angulos.map(a => `
            <div class="angulo" data-id="${a.angle_id}">
              <span class="id">${a.angle_id}</span>${a.name} — ${a.premise}
            </div>`).join("")}
        </div>
        <div class="fila-botones">
          <button id="btn-run-hooks" disabled>Generar hooks</button>
        </div>
        <div id="resultado-etapa"></div>
      `;
      let elegido = null;
      zona.querySelectorAll(".angulo").forEach(el => el.addEventListener("click", () => {
        zona.querySelectorAll(".angulo").forEach(x => x.classList.remove("elegido"));
        el.classList.add("elegido");
        elegido = el.dataset.id;
        document.getElementById("btn-run-hooks").disabled = false;
      }));
      document.getElementById("btn-run-hooks").addEventListener("click", () =>
        correrEtapa("hooks", { angle_id: elegido }));
    } else {
      zona.innerHTML = `<h2>Agente 3 · Hooks</h2><div id="resultado-etapa"></div>`;
      mostrarHooksParaAprobar(artefactos);
    }
    return;
  }

  if (etapa === "script") {
    const hooks = ultimoArtefacto(artefactos, "hooks");
    if (!pendienteAprobacion) {
      const lista = hooks ? [...hooks.payload.hooks].sort(
        (a, b) => promedioHook(b) - promedioHook(a)) : [];
      zona.innerHTML = `
        <h2>Agente 4 · Guion</h2>
        <p class="costo">Elige el hook ganador:</p>
        <div id="lista-hooks">
          ${lista.map(h => `
            <div class="hook" data-id="${h.hook_id}">
              <span class="score">${promedioHook(h).toFixed(1)}</span>
              <span class="id">${h.hook_id}</span>${h.type} — "${h.text}"
            </div>`).join("")}
        </div>
        <label>Duración objetivo (segundos)</label>
        <input id="input-duracion" type="number" value="35" min="10" max="90">
        <div class="fila-botones">
          <button id="btn-run-script" disabled>Generar guion</button>
        </div>
        <div id="resultado-etapa"></div>
      `;
      let elegido = null;
      zona.querySelectorAll(".hook").forEach(el => el.addEventListener("click", () => {
        zona.querySelectorAll(".hook").forEach(x => x.classList.remove("elegido"));
        el.classList.add("elegido");
        elegido = el.dataset.id;
        document.getElementById("btn-run-script").disabled = false;
      }));
      document.getElementById("btn-run-script").addEventListener("click", () =>
        correrEtapa("script", {
          hook_id: elegido,
          target_duration_sec: parseFloat(document.getElementById("input-duracion").value),
        }));
    } else {
      zona.innerHTML = `<h2>Agente 4 · Guion</h2><div id="resultado-etapa"></div>`;
      mostrarGuionParaAprobar(artefactos);
    }
    return;
  }

  zona.innerHTML = `
    <h2>Etapa: ${ETAPA_ES[etapa] || etapa}</h2>
    <p class="proximamente">Esta etapa todavía no tiene panel — imagen, video,
    voz y auditoría llegan en el siguiente paso del proyecto.</p>
  `;
}

function promedioHook(h) {
  const s = h.scores;
  return (s.curiosidad + s.claridad + s.pattern_interrupt + s.relevancia
          + s.ugc_fit + s.visual_ease) / 6;
}

// ------------------------------------------------- mostrar para aprobar

function mostrarAngulosParaAprobar(artefactos) {
  const strategy = ultimoArtefacto(artefactos, "strategy");
  if (!strategy) return;
  const div = document.getElementById("resultado-etapa");
  div.innerHTML = `
    <p class="costo" style="margin-top:14px;">Ángulos propuestos:</p>
    ${strategy.payload.angles.map(a => `
      <div class="angulo">
        <span class="id">${a.angle_id}</span>${a.name} — ${a.premise}
        <div style="color:var(--text-dim); font-size:12px; margin-top:4px;">
          emoción: ${a.emotion} · formato: ${a.recommended_format}
        </div>
      </div>`).join("")}
    ${botonesAprobarRechazar()}
  `;
  cablearAprobarRechazar();
}

function mostrarHooksParaAprobar(artefactos) {
  const hooks = ultimoArtefacto(artefactos, "hooks");
  if (!hooks) return;
  const div = document.getElementById("resultado-etapa");
  const lista = [...hooks.payload.hooks].sort((a, b) => promedioHook(b) - promedioHook(a));
  div.innerHTML = `
    <p class="costo" style="margin-top:14px;">Banco de hooks (ordenados por promedio):</p>
    ${lista.map(h => `
      <div class="hook">
        <span class="score">${promedioHook(h).toFixed(1)}</span>
        <span class="id">${h.hook_id}</span>${h.type} — "${h.text}"
      </div>`).join("")}
    ${botonesAprobarRechazar()}
  `;
  cablearAprobarRechazar();
}

function mostrarGuionParaAprobar(artefactos) {
  const script = ultimoArtefacto(artefactos, "ugc_script");
  if (!script) return;
  const div = document.getElementById("resultado-etapa");
  div.innerHTML = `
    <p class="costo" style="margin-top:14px;">
      Guion (${script.payload.total_duration_sec}s):
    </p>
    ${script.payload.clips.map(c => `
      <div style="font-size:13px; padding:6px 0; border-bottom:1px solid var(--border);">
        <b>${c.clip_id}</b> [${c.start}s–${c.end}s] <i>${c.role}</i><br>
        "${c.dialogue}"
      </div>`).join("")}
    <p style="margin-top:10px; font-size:13px;"><b>CTA:</b> ${script.payload.cta}</p>
    ${botonesAprobarRechazar()}
  `;
  cablearAprobarRechazar();
}

function botonesAprobarRechazar() {
  return `
    <div class="fila-botones">
      <button id="btn-aprobar">Aprobar y continuar</button>
      <button id="btn-rechazar" class="peligro">Rechazar</button>
    </div>
    <div id="area-feedback" style="display:none; margin-top:10px;">
      <label>Motivo del rechazo (se usa para reintentar)</label>
      <textarea id="input-feedback" rows="2"></textarea>
      <div class="fila-botones">
        <button id="btn-confirmar-rechazo" class="peligro">Confirmar rechazo</button>
      </div>
    </div>
  `;
}

function cablearAprobarRechazar() {
  document.getElementById("btn-aprobar").addEventListener("click", async () => {
    try {
      await api(`/projects/${proyectoActual}/stages/approve`, { method: "POST" });
      await cargarProyecto();
    } catch (err) {
      alert("No se pudo aprobar: " + err.message);
    }
  });
  document.getElementById("btn-rechazar").addEventListener("click", () => {
    document.getElementById("area-feedback").style.display = "block";
  });
  document.getElementById("btn-confirmar-rechazo").addEventListener("click", async () => {
    try {
      await api(`/projects/${proyectoActual}/stages/reject`, { method: "POST" });
      await cargarProyecto();
    } catch (err) {
      alert("No se pudo rechazar: " + err.message);
    }
  });
}

// --------------------------------------------------------- correr etapa

async function correrEtapa(nombre, datos) {
  const resultado = document.getElementById("resultado-etapa");
  resultado.innerHTML = `<p class="costo">Ejecutando… puede tardar unos segundos.</p>`;
  try {
    const salida = await api(`/projects/${proyectoActual}/stages/${nombre}`, {
      method: "POST", body: JSON.stringify(datos),
    });
    if (salida.status === "failed" && salida.issues?.length) {
      resultado.innerHTML = `
        <p class="costo" style="margin-top:10px;">No superó los criterios de calidad:</p>
        ${salida.issues.map(i => `
          <div class="issue ${i.severity}"><b>${i.code}</b>: ${i.message}</div>
        `).join("")}
        <div class="fila-botones">
          <button id="btn-reintentar">Reintentar</button>
        </div>
      `;
      document.getElementById("btn-reintentar")?.addEventListener("click",
        () => cargarProyecto());
    } else {
      await cargarProyecto();
    }
  } catch (err) {
    resultado.innerHTML = `<div class="error-msg">${err.message}</div>`;
  }
}

iniciar();
