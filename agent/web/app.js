/**
 * AutoCAD IA — Lógica de Aplicación Frontend
 * Inicialización segura y comunicación SSE con el agente
 */

let AppState = {
  servidor: null,
  trabajando: false,
  autoPlano: true,
  zoomNivel: 1,
  planUrlActual: null,
  isPanning: false,
  panStartX: 0,
  panStartY: 0,
  scrollLeft: 0,
  scrollTop: 0,
  adjuntos: [],           // Croquis/fotos pendientes de enviar
  soportaImagenes: false, // Si el modelo elegido puede verlas
  cronometro: null,       // Segundero mientras AutoCAD plotea la captura
  capturando: false,      // Hay un plot en curso: no pedir otro
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ==========================================================================
// PREFERENCIAS — guardadas en el SERVIDOR, no en el navegador
// ==========================================================================
// localStorage es por ORIGEN: cambiar el puerto del servidor (8770 -> 8771)
// hace que el navegador vea otro sitio y los ajustes desaparezcan. También
// se perdían al limpiar datos o al abrir desde otro navegador. Ahora viven
// al lado de las credenciales, en el disco, y sobreviven a todo eso.
// localStorage queda como espejo para que la primera pintada no parpadee.
let PREFS = {};

function pref(clave, porDefecto = null) {
  if (PREFS[clave] !== undefined && PREFS[clave] !== null) return PREFS[clave];
  const local = localStorage.getItem('autocad_ia_' + clave);
  return local !== null ? local : porDefecto;
}

/** El modelo elegido para cada proveedor, dentro de las preferencias. */
function guardarModeloDe(proveedor, modelo) {
  const mapa = Object.assign({}, pref('modelos', {}) || {});
  mapa[proveedor] = modelo;
  guardarPref('modelos', mapa);
}

let _guardadoPendiente = null;
function guardarPref(clave, valor) {
  PREFS[clave] = valor;
  try { localStorage.setItem('autocad_ia_' + clave, valor); } catch {}
  // Se agrupan los cambios: mover el slider de temperatura dispararía una
  // escritura por pixel.
  clearTimeout(_guardadoPendiente);
  _guardadoPendiente = setTimeout(() => {
    fetch('/api/preferencias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preferencias: PREFS }),
    }).catch(() => {});
  }, 400);
}

// ==========================================================================
// ESTADO DEL PLUGIN DE AUTOCAD
// ==========================================================================
// Antes esto no se veía en ningún lado: había que pedirle algo al agente y
// esperar (y si el perfil no tenía la tool 'ping', ni eso). Ahora se
// consulta solo, cada 15s, contra /api/autocad_estado — que no le cuesta
// un token a nadie y contesta en ~1.5s como mucho aunque AutoCAD esté
// cerrado.
async function actualizarEstadoAutoCAD() {
  const badge = $('#acad-status');
  if (!badge) return;
  try {
    const res = await fetch('/api/autocad_estado');
    const datos = await res.json();
    if (datos.conectado) {
      badge.className = 'status-badge live';
      const version = datos.pluginVersion || datos.version;
      badge.textContent = '🔌 AutoCAD: conectado' + (version ? ` (v${version})` : '');
      badge.title = 'El plugin respondió al último chequeo.';
    } else {
      badge.className = 'status-badge acad-off';
      badge.textContent = '🔌 AutoCAD: sin conectar';
      badge.title = datos.detalle || 'Abrí AutoCAD con el plugin cargado.';
    }
  } catch {
    badge.className = 'status-badge acad-off';
    badge.textContent = '🔌 AutoCAD: sin conectar';
    badge.title = 'No se pudo consultar el estado.';
  }
}

// ==========================================================================
// ARRANQUE DE LA APLICACIÓN
// ==========================================================================
async function init() {
  try {
    const res = await fetch('/api/estado');
    if (!res.ok) throw new Error('No se pudo comunicar con el backend local');
    AppState.servidor = await res.json();
    PREFS = AppState.servidor.preferencias || {};

    poblarOpciones();
    cargarConfiguracionGuardada();
    aplicarPreferencias();
    const varios = elegirProveedorInicial();
    renderizarConfiguracion();

    const p = getProveedorActual();
    const configurado = pref('configurado');
    const saltar = new URLSearchParams(location.search).has('skip');

    if (varios && !saltar) {
      // Hay más de un proveedor con clave: que elija, en vez de arrancar
      // en uno cualquiera y que después no entienda por qué está usando
      // ese. Se pregunta UNA vez; después queda recordado.
      preguntarCualProveedor(varios);
    } else if (!p?.clave && !configurado && p?.id !== 'local' && !saltar) {
      abrirWizard(0);
    }
  } catch (err) {
    console.error('Error inicializando:', err);
    showToast('Error conectando al backend: ' + err.message, 'error');
    const conn = $('#connection-status');
    if (conn) {
      conn.className = 'status-badge';
      conn.textContent = '● Sin conexión';
    }
  }

  registrarEventos();
  actualizarEstadoAutoCAD();
  setInterval(actualizarEstadoAutoCAD, 15000);
}

function poblarOpciones() {
  if (!AppState.servidor) return;
  const { proveedores, perfiles } = AppState.servidor;

  const opsProveedores = proveedores.map(p => 
    `<option value="${p.id}">${p.id.toUpperCase()}</option>`
  ).join('');

  const selProv = $('#select-provider');
  const wizProv = $('#wizard-provider');
  if (selProv) selProv.innerHTML = opsProveedores;
  if (wizProv) wizProv.innerHTML = opsProveedores;

  const selProf = $('#select-profile');
  if (selProf) {
    selProf.innerHTML = perfiles.map(p =>
      `<option value="${p.id}" ${p.id === 'arquitectura' ? 'selected' : ''}>` +
      `${p.id.charAt(0).toUpperCase() + p.id.slice(1)} (${p.tools} tools)</option>`
    ).join('');
  }
}

/** Vuelve a poner en la interfaz los ajustes de la sesión anterior. */
function aplicarPreferencias() {
  const perfil = pref('perfil');
  const selProf = $('#select-profile');
  if (perfil && selProf
      && [...selProf.options].some(o => o.value === perfil)) {
    selProf.value = perfil;
  }

  const temp = pref('temperatura');
  const inTemp = $('#input-temp');
  if (temp !== null && inTemp) {
    inTemp.value = temp;
    const salida = $('#temp-val');
    if (salida) salida.textContent = parseFloat(temp).toFixed(1);
  }

  const reglas = pref('conReglas');
  const chk = $('#check-rules');
  // Viene como booleano del servidor o como "true"/"false" del navegador.
  if (reglas !== null && chk) chk.checked = (reglas === true || reglas === 'true');
}

function cargarConfiguracionGuardada() {
  const prov = pref('proveedor');
  if (prov && AppState.servidor?.proveedores?.some(p => p.id === prov)) {
    const selProv = $('#select-provider');
    const wizProv = $('#wizard-provider');
    if (selProv) selProv.value = prov;
    if (wizProv) wizProv.value = prov;
  }
}

/**
 * Si no hay preferencia guardada, arrancar en un proveedor QUE TENGA CLAVE.
 * Sin esto la app abre en el primero de la lista (anthropic), lo ve sin
 * configurar y muestra el asistente a alguien que ya tenía todo listo en
 * otro proveedor.
 * Devuelve la lista de configurados SOLO si hay más de uno (para
 * preguntar cuál); null si no hay que preguntar nada.
 */
function elegirProveedorInicial() {
  if (pref('proveedor')) return null;
  const listos = (AppState.servidor?.proveedores || [])
    .filter(p => p.clave);
  if (!listos.length) return null;

  const selProv = $('#select-provider');
  const wizProv = $('#wizard-provider');
  if (selProv) selProv.value = listos[0].id;
  if (wizProv) wizProv.value = listos[0].id;

  return listos.length > 1 ? listos : null;
}

/** Pregunta con cuál de los proveedores configurados trabajar. */
function preguntarCualProveedor(listos) {
  const msgs = $('#chat-messages');
  if (!msgs) return;
  limpiarVacio();
  const caja = document.createElement('div');
  caja.className = 'provider-picker';
  caja.innerHTML =
    `<div class="picker-title">Tenés ${listos.length} proveedores con clave. ` +
    `¿Con cuál trabajamos?</div><div class="picker-options"></div>`;
  const cont = caja.querySelector('.picker-options');

  listos.forEach(p => {
    const b = document.createElement('button');
    b.className = 'btn btn-accent picker-option';
    b.innerHTML = `<b>${p.id.toUpperCase()}</b><small>${p.clave}</small>`;
    b.onclick = () => {
      const selProv = $('#select-provider');
      if (selProv) selProv.value = p.id;
      guardarPref('proveedor', p.id);
      renderizarConfiguracion();
      caja.remove();
      showToast(`Trabajando con ${p.id.toUpperCase()}`, 'success');
    };
    cont.appendChild(b);
  });

  msgs.appendChild(caja);
}

function getProveedorActual() {
  const selProv = $('#select-provider');
  const id = selProv ? selProv.value : (AppState.servidor?.proveedores?.[0]?.id || 'anthropic');
  return AppState.servidor?.proveedores?.find(p => p.id === id);
}

function renderizarConfiguracion() {
  const p = getProveedorActual();
  if (!p) return;

  guardarPref('proveedor', p.id);

  const chip = $('#key-status-chip');
  if (chip) {
    if (p.clave) {
      const modo = p.proteccion === 'dpapi' ? 'cifrada' : 'almacenada';
      chip.className = 'chip-status encrypted';
      chip.innerHTML = `<span>${p.clave} (${modo})</span>`;
    } else if (p.id === 'local') {
      chip.className = 'chip-status';
      chip.innerHTML = `<span>Local (sin clave)</span>`;
    } else {
      chip.className = 'chip-status warning';
      chip.innerHTML = `<span>Sin clave guardada</span>`;
    }
  }

  const inModel = $('#input-model');
  if (inModel) {
    const modeloGuardado = (pref('modelos', {}) || {})[p.id];
    inModel.value = modeloGuardado || p.modeloSugerido;
  }

  const modelList = $('#model-list-container');
  if (modelList) modelList.innerHTML = '';

  actualizarSubtitulo();
}

function actualizarSubtitulo() {
  // Cambió el modelo: puede haber dejado de aceptar imágenes (o empezado).
  // Se engancha acá porque es el único punto por el que pasan TODAS las
  // formas de cambiar de modelo: escribirlo, elegirlo de la lista o
  // cambiar de proveedor.
  refrescarSoporteImagenes();
  const p = getProveedorActual();
  const inModel = $('#input-model');
  const m = (inModel ? inModel.value.trim() : '') || '(sin modelo)';
  const sub = $('#session-subtitle');
  if (sub) {
    sub.textContent = `${m} · ${p ? p.id : ''}`;
  }
}

// ==========================================================================
// CLAVES Y MODELOS
// ==========================================================================
async function guardarClave(clave) {
  const p = getProveedorActual();
  try {
    const res = await fetch('/api/clave', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proveedor: p.id, clave }),
    });
    const data = await res.json();
    if (data.error) {
      showToast(data.error, 'error');
      return false;
    }
    p.clave = data.clave;
    p.proteccion = data.proteccion;
    renderizarConfiguracion();
    showToast('Clave guardada y cifrada', 'success');
    return true;
  } catch (err) {
    showToast('Error al guardar: ' + err.message, 'error');
    return false;
  }
}

async function borrarClave() {
  const p = getProveedorActual();
  if (!confirm(`¿Eliminar la clave guardada para ${p.id}?`)) return;
  try {
    await fetch('/api/clave', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proveedor: p.id, borrar: true }),
    });
    p.clave = null;
    p.proteccion = null;
    renderizarConfiguracion();
    showToast('Clave eliminada', 'success');
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
}

async function listarModelos(probar = false) {
  const p = getProveedorActual();
  const c = $('#model-list-container');
  if (!c) return;

  c.innerHTML = `
    <div style="font-size:11px;color:var(--text-muted);padding:6px;">
      ${probar ? '⚡ Probando compatibilidad con AutoCAD…' : '🔍 Obteniendo catálogo…'}
    </div>`;

  try {
    const res = await fetch('/api/modelos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proveedor: p.id, probar }),
    });
    const data = await res.json();
    if (data.error) {
      c.innerHTML = '';
      showToast(data.error, 'error');
      return;
    }

    if (!data.modelos?.length) {
      c.innerHTML = `<div style="font-size:11px;color:var(--text-dim);padding:4px;">No se encontraron modelos.</div>`;
      return;
    }

    const inModel = $('#input-model');
    const modeloActual = inModel ? inModel.value.trim() : '';

    c.innerHTML = data.modelos.map(m => {
      const isOk = m.estado.startsWith('OK');
      const isErr = /bloquead|error|sin respuesta|no/.test(m.estado.toLowerCase());
      const isSelected = m.modelo === modeloActual;
      return `
        <div class="model-item ${isOk ? 'ok' : isErr ? 'err' : ''} ${isSelected ? 'selected' : ''}" data-model="${m.modelo}">
          <span>${m.modelo}</span>
          <span class="model-badge">${m.estado === '?' ? 'disponible' : m.estado}</span>
        </div>
      `;
    }).join('');

    $$('.model-item').forEach(el => {
      el.onclick = () => {
        const m = el.dataset.model;
        if (inModel) inModel.value = m;
        guardarModeloDe(p.id, m);
        $$('.model-item').forEach(x => x.classList.remove('selected'));
        el.classList.add('selected');
        actualizarSubtitulo();
      };
    });
  } catch (err) {
    c.innerHTML = '';
    showToast('Error al consultar modelos: ' + err.message, 'error');
  }
}

// ==========================================================================
// CHAT & STREAMING SSE
// ==========================================================================
function limpiarVacio() {
  const el = $('#empty-state-view');
  if (el) el.remove();
}

function scrollAbajo() {
  const msgs = $('#chat-messages');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

// El modelo contesta en Markdown (**negrita**, `code`, citas con "> ",
// listas con "- "): antes se mostraba tal cual, asteriscos y todo, en vez
// de formateado. Sin librería — es el mismo criterio del resto del
// proyecto ("http.server viene con Python", ni una dependencia de más — y
// esto sigue esa misma línea del lado del navegador) — y solo el subset
// que el agente realmente usa; nada de tablas, imágenes ni encabezados.
function escaparHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatearMarkdown(texto) {
  const enlinea = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  const bloques = [];
  let parrafo = [];
  let lista = [];
  let cita = [];
  const cerrarParrafo = () => {
    if (parrafo.length) { bloques.push(`<p>${parrafo.join('<br>')}</p>`); parrafo = []; }
  };
  const cerrarLista = () => {
    if (lista.length) { bloques.push(`<ul>${lista.join('')}</ul>`); lista = []; }
  };
  const cerrarCita = () => {
    if (cita.length) { bloques.push(`<blockquote>${cita.join('<br>')}</blockquote>`); cita = []; }
  };

  for (const linea of escaparHtml(texto).split('\n')) {
    const l = linea.trim();
    if (l.startsWith('&gt; ') || l === '&gt;') {
      cerrarParrafo(); cerrarLista();
      cita.push(enlinea(l.replace(/^&gt;\s?/, '')));
    } else if (/^[-*]\s+/.test(l)) {
      cerrarParrafo(); cerrarCita();
      lista.push(`<li>${enlinea(l.replace(/^[-*]\s+/, ''))}</li>`);
    } else if (l === '') {
      cerrarParrafo(); cerrarLista(); cerrarCita();
    } else {
      cerrarLista(); cerrarCita();
      parrafo.push(enlinea(l));
    }
  }
  cerrarParrafo(); cerrarLista(); cerrarCita();
  return bloques.join('') || '';
}

function agregarBurbuja(autor, texto, esUsuario = false, adjuntos = []) {
  limpiarVacio();
  const msgs = $('#chat-messages');
  if (!msgs) return;
  const row = document.createElement('div');
  row.className = `message-row ${esUsuario ? 'user' : 'assistant'}`;
  row.innerHTML = `
    <div class="message-author">${esUsuario ? 'Tú' : 'AutoCAD IA'}</div>
    <div class="message-bubble"></div>
  `;
  const burbuja = row.querySelector('.message-bubble');
  // El texto del usuario se muestra tal cual escribió (no interpretamos SU
  // markdown); la respuesta del agente sí se formatea.
  if (esUsuario) {
    burbuja.textContent = texto;
  } else {
    burbuja.innerHTML = formatearMarkdown(texto);
  }
  // Las imágenes enviadas quedan en el hilo: si después el agente dice
  // algo raro, se puede ver qué fue exactamente lo que miró.
  if (adjuntos.length) {
    const tira = document.createElement('div');
    tira.className = 'message-images';
    tira.innerHTML = adjuntos
      .map(a => `<img src="${a.dataUrl}" alt="${a.nombre}" title="${a.nombre}">`)
      .join('');
    burbuja.appendChild(tira);
  }
  msgs.appendChild(row);
  scrollAbajo();
}

function agregarToolCard(nombre, args, estado = 'running') {
  limpiarVacio();
  const msgs = $('#chat-messages');
  if (!msgs) return;
  const card = document.createElement('div');
  card.className = `tool-card ${estado}`;
  
  let badge = 'EJECUTANDO';
  if (estado === 'success') badge = 'OK';
  if (estado === 'error') badge = 'ERROR';

  card.innerHTML = `
    <div class="tool-card-icon">[${badge}]</div>
    <div class="tool-card-body">
      <div class="tool-card-header">
        <span class="tool-card-name">${nombre}</span>
      </div>
      <div class="tool-card-details"></div>
    </div>
  `;
  card.querySelector('.tool-card-details').textContent = args;
  msgs.appendChild(card);
  scrollAbajo();
}

function agregarAvisoChat(texto) {
  limpiarVacio();
  const msgs = $('#chat-messages');
  if (!msgs) return;
  const notice = document.createElement('div');
  notice.className = 'chat-notice';
  // Estos avisos pueden traer texto de un error o de la respuesta cruda
  // de una tool: se escapa antes de meterlo en innerHTML por lo mismo que
  // el burbujeo de arriba, no porque haya markdown que mostrar acá.
  notice.innerHTML = `<div>${escaparHtml(texto)}</div>`;
  msgs.appendChild(notice);
  scrollAbajo();
}

const REGEX_DIBUJO = /^(create_|draw_|place_|suggest_furniture|dimension_|label_|union_|compose_|delete_|move_|offset_|mirror_|array_|copy_|rotate_|scale_)/;

// ==========================================================================
// ADJUNTOS (CROQUIS / FOTOS)
// ==========================================================================
// Un modelo de solo texto NO puede ver una imagen: unos la ignoran en
// silencio -- y entonces contestan sobre algo que no miraron -- y otros
// rechazan el pedido entero con un 400 críptico. Por eso el botón se
// habilita SOLO cuando el modelo elegido es multimodal, y cuando no lo es
// dice por qué en vez de dejar adjuntar algo que no va a servir.
const MAX_ADJUNTO_MB = 4;

async function refrescarSoporteImagenes() {
  const btn = $('#btn-attach');
  if (!btn) return;
  const inModel = $('#input-model');
  const modelo = inModel ? inModel.value.trim() : '';
  if (!modelo) { btn.disabled = true; return; }

  try {
    const r = await (await fetch('/api/vision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modelo }),
    })).json();

    AppState.soportaImagenes = !!r.soportaImagenes;
    btn.disabled = !r.soportaImagenes;
    btn.classList.toggle('no-vision', !r.soportaImagenes);
    btn.title = r.soportaImagenes
      ? 'Adjuntar croquis o foto (el modelo puede verla)'
      : r.motivo;
    if (!r.soportaImagenes && AppState.adjuntos.length) limpiarAdjuntos();
  } catch {
    btn.disabled = true;
  }
}

function limpiarAdjuntos() {
  AppState.adjuntos = [];
  const cont = $('#attach-preview');
  if (cont) { cont.innerHTML = ''; cont.classList.add('hidden'); }
}

function pintarAdjuntos() {
  const cont = $('#attach-preview');
  if (!cont) return;
  cont.classList.toggle('hidden', !AppState.adjuntos.length);
  cont.innerHTML = AppState.adjuntos.map((a, i) => `
    <div class="attach-chip">
      <img src="${a.dataUrl}" alt="">
      <span>${a.nombre}</span>
      <button class="attach-remove" data-i="${i}" title="Quitar">✕</button>
    </div>`).join('');
  cont.querySelectorAll('.attach-remove').forEach(b => b.onclick = () => {
    AppState.adjuntos.splice(+b.dataset.i, 1);
    pintarAdjuntos();
  });
}

async function agregarArchivos(archivos) {
  if (!AppState.soportaImagenes) {
    showToast('El modelo elegido no puede ver imágenes', 'error');
    return;
  }
  for (const f of archivos) {
    if (!f.type.startsWith('image/')) {
      showToast(`"${f.name}" no es una imagen`, 'error');
      continue;
    }
    if (f.size > MAX_ADJUNTO_MB * 1024 * 1024) {
      showToast(`"${f.name}" pesa más de ${MAX_ADJUNTO_MB} MB`, 'error');
      continue;
    }
    const dataUrl = await new Promise(res => {
      const fr = new FileReader();
      fr.onload = () => res(fr.result);
      fr.readAsDataURL(f);
    });
    AppState.adjuntos.push({ nombre: f.name, dataUrl });
  }
  pintarAdjuntos();
}

async function enviarMensaje() {
  const inChat = $('#chat-input');
  const texto = inChat ? inChat.value.trim() : '';
  if ((!texto && !AppState.adjuntos.length) || AppState.trabajando) return;

  const p = getProveedorActual();
  if (!p.clave && p.id !== 'local') {
    showToast(`Configurá tu API key de ${p.id} antes de continuar`, 'error');
    return;
  }

  if (inChat) {
    inChat.value = '';
    inChat.style.height = 'auto';
  }
  const adjuntos = AppState.adjuntos.slice();
  agregarBurbuja('Tú', texto || '(imagen adjunta)', true, adjuntos);
  limpiarAdjuntos();

  AppState.trabajando = true;
  const btnSend = $('#btn-send');
  const btnCancel = $('#btn-cancel');
  const typing = $('#typing-indicator');
  const inModel = $('#input-model');
  const selProf = $('#select-profile');
  const chkRules = $('#check-rules');
  const inTemp = $('#input-temp');

  if (btnSend) btnSend.disabled = true;
  if (btnCancel) btnCancel.style.display = 'inline-flex';
  if (typing) typing.style.display = 'inline-flex';

  let huboDibujo = false;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mensaje: texto,
        imagenes: adjuntos.map(a => a.dataUrl),
        proveedor: p.id,
        modelo: inModel ? inModel.value.trim() : '',
        perfil: selProf ? selProf.value : 'arquitectura',
        conReglas: chkRules ? chkRules.checked : true,
        temperatura: inTemp ? parseFloat(inTemp.value) : 0.2,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      agregarAvisoChat(err.error || `El servidor respondió con código ${res.status}`);
    } else {
      huboDibujo = await procesarSSE(res);
    }
  } catch (err) {
    agregarAvisoChat('Se cortó la conexión: ' + err.message);
  } finally {
    AppState.trabajando = false;
    if (btnSend) btnSend.disabled = false;
    if (btnCancel) btnCancel.style.display = 'none';
    if (typing) typing.style.display = 'none';

    if (huboDibujo && AppState.autoPlano) {
      capturarPlano();
    }
  }
}

async function procesarSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let realizoDibujo = false;
  let terminado = false;

  while (!terminado) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lineas = buffer.split('\n\n');
    buffer = lineas.pop();

    for (const linea of lineas) {
      const dataLine = linea.split('\n').find(x => x.startsWith('data: '));
      if (!dataLine) continue;

      try {
        const ev = JSON.parse(dataLine.slice(6));
        // 'fin' es la señal real de que no viene nada más — no confiar
        // solo en el 'done' del stream para cortar acá: si el servidor
        // deja la conexión mal cerrada (pasó de verdad, ver web.py), el
        // reader se queda esperando para siempre y el chat entero se
        // traba con "Agente procesando…" y Enviar bloqueado.
        if (ev.tipo === 'fin') {
          terminado = true;
          break;
        }
        if (despacharEvento(ev)) {
          realizoDibujo = true;
        }
      } catch {}
    }
  }
  try { await reader.cancel(); } catch {}
  return realizoDibujo;
}

function despacharEvento(ev) {
  if (ev.tipo === 'inicio') {
    const sub = $('#session-subtitle');
    if (sub) sub.textContent = `${ev.modelo} · ${ev.tools} tools`;
  } else if (ev.tipo === 'uso') {
    const tokenPill = $('#token-counter');
    const totTokens = $('#total-tokens');
    const totTurns = $('#total-turns');
    if (tokenPill) tokenPill.style.display = 'flex';
    if (totTokens) totTokens.textContent = ev.total.toLocaleString('es');
    if (totTurns) totTurns.textContent = ev.vueltas;
  } else if (ev.tipo === 'texto') {
    agregarBurbuja('AutoCAD IA', ev.texto, false);
  } else if (ev.tipo === 'tool') {
    let argsStr = JSON.stringify(ev.args, null, 2);
    if (argsStr.length > 200) argsStr = argsStr.slice(0, 197) + '…';
    agregarToolCard(ev.nombre, argsStr, 'running');
  } else if (ev.tipo === 'resultado') {
    let resStr = (ev.texto || '').replace(/\s+/g, ' ');
    if (resStr.length > 200) resStr = resStr.slice(0, 197) + '…';
    agregarToolCard((ev.error ? 'Error: ' : '✓ ') + ev.nombre, resStr, ev.error ? 'error' : 'success');
    if (!ev.error && REGEX_DIBUJO.test(ev.nombre)) {
      return true;
    }
  } else if (ev.tipo === 'aviso') {
    agregarAvisoChat(ev.texto);
  }
  return false;
}

// ==========================================================================
// VISOR DE PLANO (DWG VIEWPORT)
// ==========================================================================
// El plot de AutoCAD tarda ~7 s y no hay forma de acelerarlo desde acá. Lo
// que SÍ se puede es no dejar el panel en blanco y mudo todo ese rato: sin
// el segundero, una espera normal se lee como un visor roto.
function arrancarCronometro() {
  const marca = $('#capture-elapsed');
  if (!marca) return null;
  const t0 = Date.now();
  return setInterval(() => {
    marca.textContent = `${((Date.now() - t0) / 1000).toFixed(1)} s`;
  }, 100);
}

function pararCronometro() {
  if (AppState.cronometro) clearInterval(AppState.cronometro);
  AppState.cronometro = null;
}

async function capturarPlano(zona = null) {
  const layout = $('#app-layout');
  const canvas = $('#plan-canvas-wrapper');
  if (layout) layout.classList.add('con-plano');
  // Un clic más mientras AutoCAD plotea no lo apura: lo encola detrás y el
  // visor tarda el doble. El servidor también lo frena, pero mejor ni
  // pedirlo.
  if (AppState.capturando) {
    showToast('Ya hay una captura en curso, esperá a que termine', 'info');
    return;
  }
  AppState.capturando = true;
  const btnRef = $('#btn-refresh-plan');
  if (btnRef) btnRef.disabled = true;
  pararCronometro();
  if (canvas) {
    canvas.className = 'viewer-canvas-wrapper empty-canvas';
    canvas.innerHTML = `
      <div class="typing-dots"><span></span><span></span><span></span></div>
      <div style="font-size:13px;color:var(--text-muted);margin-top:8px;">Ploteando la vista en AutoCAD…</div>
      <div id="capture-elapsed" style="font-family:var(--font-mono);font-size:20px;color:var(--text-main);margin-top:6px;">0.0 s</div>
      <div style="font-size:11.5px;color:var(--text-muted);margin-top:2px;">suele tardar unos 7 segundos</div>
    `;
    AppState.cronometro = arrancarCronometro();
  }

  try {
    const res = await fetch('/api/captura', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zona }),
    });
    const data = await res.json();
    pararCronometro();
    AppState.capturando = false;
    if (btnRef) btnRef.disabled = false;
    if (data.ok) {
      mostrarPlano(data);
    } else {
      if (canvas) {
        canvas.innerHTML = `
          <div style="color:var(--error);text-align:center;padding:20px;">
            ✕ ${data.error || 'No se pudo obtener la captura.'}
          </div>
        `;
      }
    }
  } catch (err) {
    pararCronometro();
    AppState.capturando = false;
    if (btnRef) btnRef.disabled = false;
    if (canvas) {
      canvas.innerHTML = `<div style="color:var(--error);padding:20px;">${err.message}</div>`;
    }
  }
}

function mostrarPlano(data) {
  AppState.zoomNivel = 1;
  AppState.planUrlActual = data.url;
  const canvas = $('#plan-canvas-wrapper');
  if (canvas) {
    canvas.className = 'viewer-canvas-wrapper';
    canvas.innerHTML = `<img id="plan-image" src="${data.url}" alt="Plano AutoCAD" draggable="false">`;
  }

  actualizarZoom(0);

  const ext = data.extension;
  const foot = $('#plan-footer-info');
  if (foot) {
    if (ext && !ext.isEmpty) {
      const w = (ext.width || 0).toFixed(2);
      const h = (ext.height || 0).toFixed(2);
      const ent = ext.entities || 0;
      foot.textContent = `${w} × ${h} m · ${ent} entidades`;
    } else {
      foot.textContent = 'Vista general';
    }
  }
}

function actualizarZoom(delta) {
  if (delta === 0) AppState.zoomNivel = 1;
  else AppState.zoomNivel = Math.max(0.4, Math.min(5, AppState.zoomNivel + delta));

  const img = $('#plan-image');
  if (img) img.style.transform = `scale(${AppState.zoomNivel})`;
  const zInfo = $('#plan-zoom-info');
  if (zInfo) zInfo.textContent = `${Math.round(AppState.zoomNivel * 100)}%`;
}

function descargarCaptura() {
  if (!AppState.planUrlActual) return showToast('No hay ninguna captura disponible', 'error');
  const a = document.createElement('a');
  a.href = AppState.planUrlActual;
  a.download = `plano_autocad_${Date.now()}.png`;
  a.click();
}

// ==========================================================================
// MODAL / ASISTENTE
// ==========================================================================
function abrirWizard(paso = 0) {
  const modal = $('#welcome-modal');
  if (modal) modal.classList.remove('hidden');
  irPasoWizard(paso);
}

function cerrarWizard() {
  guardarPref('configurado', '1');
  const modal = $('#welcome-modal');
  if (modal) modal.classList.add('hidden');
}

function irPasoWizard(paso) {
  $$('.wizard-step-pane').forEach((el, idx) => {
    el.classList.toggle('active', idx === paso);
  });
  $$('.wizard-progress-step').forEach((el, idx) => {
    el.classList.toggle('active', idx <= paso);
  });

  if (paso === 0) {
    actualizarHintWizard();
  } else if (paso === 1) {
    const p = getProveedorActual();
    const wChip = $('#wizard-key-status-chip');
    if (wChip) {
      if (p?.clave) {
        wChip.className = 'chip-status encrypted';
        wChip.innerHTML = `🔒 Ya configurada (${p.clave})`;
      } else {
        wChip.className = 'chip-status';
        wChip.textContent = 'Sin clave guardada';
      }
    }
  } else if (paso === 2) {
    ejecutarDiagnosticos();
  }
}

function actualizarHintWizard() {
  const wizProv = $('#wizard-provider');
  const val = wizProv ? wizProv.value : 'anthropic';
  const p = AppState.servidor?.proveedores?.find(x => x.id === val);
  const hint = $('#wizard-provider-hint');
  if (!hint || !p) return;

  if (p.id === 'local') {
    hint.textContent = 'Servidor local (LM Studio / Ollama). No requiere clave de API.';
  } else {
    hint.textContent = `Requiere clave de ${p.id.toUpperCase()}` + (p.variable ? ` (o variable ${p.variable}).` : '.');
  }
}

async function ejecutarDiagnosticos() {
  const p = getProveedorActual();

  // 1. Clave
  const okClave = !!p?.clave || p?.id === 'local';
  setDiag('diag-light-key', okClave, 'diag-text-key', 
    okClave ? (p.clave || 'No requerida (local)') : 'Falta guardar la clave');

  // 2. Modelo
  setDiag('diag-light-model', null, 'diag-text-model', 'Comprobando compatibilidad de tools…');
  if (okClave) {
    try {
      const res = await fetch('/api/modelos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proveedor: p.id, probar: true }),
      });
      const data = await res.json();
      const buenos = (data.modelos || []).filter(m => m.estado.startsWith('OK'));
      if (buenos.length > 0) {
        setDiag('diag-light-model', true, 'diag-text-model', `${buenos.length} modelo(s) compatibles con AutoCAD`);
      } else {
        setDiag('diag-light-model', false, 'diag-text-model', data.error || 'Ningún modelo superó la prueba de tools');
      }
    } catch (e) {
      setDiag('diag-light-model', false, 'diag-text-model', e.message);
    }
  } else {
    setDiag('diag-light-model', false, 'diag-text-model', 'Requiere clave primero');
  }

  // 3. AutoCAD MCP
  setDiag('diag-light-cad', null, 'diag-text-cad', 'Verificando plugin de AutoCAD…');
  try {
    const res = await fetch('/api/captura', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const data = await res.json();
    if (data.ok) {
      setDiag('diag-light-cad', true, 'diag-text-cad', 'Plugin conectado y dibujo abierto');
      mostrarPlano(data);
    } else {
      setDiag('diag-light-cad', false, 'diag-text-cad', (data.error || '').slice(0, 70));
    }
  } catch (e) {
    setDiag('diag-light-cad', false, 'diag-text-cad', e.message);
  }
}

function setDiag(lightId, estado, textId, desc) {
  const el = $('#' + lightId);
  const tx = $('#' + textId);
  if (el) el.className = 'status-light ' + (estado === null ? 'loading' : estado ? 'ok' : 'error');
  if (tx) tx.textContent = desc;
}

// ==========================================================================
// TOAST & REGISTRO DE EVENTOS
// ==========================================================================
function showToast(msg, tipo = 'info') {
  const container = $('#toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = `toast ${tipo}`;
  const icon = tipo === 'success' ? '✓' : tipo === 'error' ? '✕' : 'ℹ';
  t.innerHTML = `<span>${icon}</span> <span>${msg}</span>`;
  container.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateY(8px)';
    setTimeout(() => t.remove(), 250);
  }, 3500);
}

function registrarEventos() {
  const sidebar = $('#app-sidebar');
  const backdrop = $('#sidebar-backdrop');
  const btnOpen = $('#btn-open-sidebar');
  const btnClose = $('#btn-close-sidebar');

  const abrirSidebar = () => {
    if (sidebar) sidebar.classList.add('mobile-open');
    if (backdrop) backdrop.classList.add('active');
  };
  const cerrarSidebar = () => {
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (backdrop) backdrop.classList.remove('active');
  };

  if (btnOpen) btnOpen.onclick = abrirSidebar;
  if (btnClose) btnClose.onclick = cerrarSidebar;
  if (backdrop) backdrop.onclick = cerrarSidebar;

  const inTemp = $('#input-temp');
  const tempVal = $('#temp-val');
  if (inTemp && tempVal) {
    inTemp.oninput = () => {
      tempVal.textContent = inTemp.value;
    };
  }

  const selProv = $('#select-provider');
  const wizProv = $('#wizard-provider');
  if (selProv) {
    selProv.onchange = () => {
      if (wizProv) wizProv.value = selProv.value;
      renderizarConfiguracion();
    };
  }
  if (wizProv) {
    wizProv.onchange = () => {
      if (selProv) selProv.value = wizProv.value;
      renderizarConfiguracion();
      actualizarHintWizard();
    };
  }

  const btnSaveKey = $('#btn-save-key');
  const inKey = $('#input-api-key');
  if (btnSaveKey) {
    btnSaveKey.onclick = async () => {
      const c = inKey ? inKey.value.trim() : '';
      if (!c) return showToast('Ingresá una clave', 'error');
      if (await guardarClave(c)) {
        if (inKey) inKey.value = '';
      }
    };
  }

  const btnDeleteKey = $('#btn-delete-key');
  if (btnDeleteKey) btnDeleteKey.onclick = borrarClave;

  const btnToggleKey = $('#btn-toggle-key-visibility');
  if (btnToggleKey && inKey) {
    btnToggleKey.onclick = () => {
      const isPass = inKey.type === 'password';
      inKey.type = isPass ? 'text' : 'password';
      btnToggleKey.textContent = isPass ? '🙈' : '👁️';
    };
  }

  const btnToggleWizKey = $('#btn-toggle-wizard-key');
  const inWizKey = $('#wizard-api-key');
  if (btnToggleWizKey && inWizKey) {
    btnToggleWizKey.onclick = () => {
      const isPass = inWizKey.type === 'password';
      inWizKey.type = isPass ? 'text' : 'password';
      btnToggleWizKey.textContent = isPass ? '🙈' : '👁️';
    };
  }

  const inModel = $('#input-model');
  if (inModel) {
    inModel.oninput = () => {
      const p = getProveedorActual();
      if (p) guardarModeloDe(p.id, inModel.value);
      actualizarSubtitulo();
    };
  }

  // --- Ajustes que tienen que sobrevivir al reinicio ---
  const selProfPref = $('#select-profile');
  if (selProfPref) {
    selProfPref.addEventListener('change',
      () => guardarPref('perfil', selProfPref.value));
  }
  const inTempPref = $('#input-temp');
  if (inTempPref) {
    inTempPref.addEventListener('change',
      () => guardarPref('temperatura', parseFloat(inTempPref.value)));
  }
  const chkRulesPref = $('#check-rules');
  if (chkRulesPref) {
    chkRulesPref.addEventListener('change',
      () => guardarPref('conReglas', chkRulesPref.checked));
  }

  // --- Adjuntar croquis / fotos ---
  const btnAttach = $('#btn-attach');
  const inputFile = $('#input-file');
  if (btnAttach && inputFile) {
    btnAttach.onclick = () => inputFile.click();
    inputFile.onchange = () => {
      agregarArchivos(Array.from(inputFile.files || []));
      inputFile.value = '';
    };
  }
  // Pegar con Ctrl+V y arrastrar sobre el chat: las dos formas naturales
  // de mandar una captura, sin pasar por el diálogo de archivos.
  const areaPegar = $('#chat-input');
  if (areaPegar) {
    areaPegar.addEventListener('paste', (e) => {
      const files = Array.from(e.clipboardData?.files || []);
      if (files.length) { e.preventDefault(); agregarArchivos(files); }
    });
  }
  const zonaChat = $('#chat-messages');
  if (zonaChat) {
    ['dragover', 'drop'].forEach(ev =>
      zonaChat.addEventListener(ev, (e) => {
        e.preventDefault();
        if (ev === 'drop') {
          agregarArchivos(Array.from(e.dataTransfer?.files || []));
        }
        zonaChat.classList.toggle('drag-over', ev === 'dragover');
      }));
    zonaChat.addEventListener('dragleave', () =>
      zonaChat.classList.remove('drag-over'));
  }

  const btnListModels = $('#btn-list-models');
  if (btnListModels) btnListModels.onclick = () => listarModelos(false);

  const btnTestModels = $('#btn-test-models');
  if (btnTestModels) btnTestModels.onclick = () => listarModelos(true);

  const btnNewSession = $('#btn-new-session');
  if (btnNewSession) {
    btnNewSession.onclick = async () => {
      if (!confirm('¿Reiniciar sesión? El agente olvidará los comandos previos.')) return;
      try {
        await fetch('/api/reset', { method: 'POST' });
        const msgs = $('#chat-messages');
        const tokenPill = $('#token-counter');
        if (msgs) msgs.innerHTML = '';
        if (tokenPill) tokenPill.style.display = 'none';
        showToast('Nueva sesión iniciada', 'success');
        agregarAvisoChat('Sesión reiniciada. Listo para un nuevo plano en AutoCAD.');
      } catch (e) {
        showToast('Error: ' + e.message, 'error');
      }
    };
  }

  const btnApagar = $('#btn-apagar');
  if (btnApagar) {
    btnApagar.onclick = async () => {
      if (!confirm('¿Apagar AutoCAD IA? Se cierra el servidor local — para volver a abrirlo, doble clic en AutoCAD-IA.bat.')) return;
      try {
        await fetch('/api/apagar', { method: 'POST' });
      } catch (e) {
        // el servidor puede cerrar la conexion antes de que la respuesta
        // termine de llegar - no es un error real, es justo lo que se pidio.
      }
      document.body.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;height:100vh;font:16px system-ui;color:#888;">' +
        'AutoCAD IA se apagó. Puedes cerrar esta pestaña.</div>';
    };
  }

  const btnSend = $('#btn-send');
  if (btnSend) btnSend.onclick = enviarMensaje;

  const inChat = $('#chat-input');
  if (inChat) {
    inChat.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        enviarMensaje();
      }
    });
    inChat.addEventListener('input', () => {
      inChat.style.height = 'auto';
      inChat.style.height = Math.min(inChat.scrollHeight, 150) + 'px';
    });
  }

  const btnCancel = $('#btn-cancel');
  if (btnCancel) {
    btnCancel.onclick = async () => {
      try {
        await fetch('/api/cancelar', { method: 'POST' });
        showToast('Cancelando tras la herramienta actual…', 'info');
      } catch (e) {
        showToast('Error: ' + e.message, 'error');
      }
    };
  }

  // Clic en tarjetas de sugerencia y plantillas
  document.addEventListener('click', (e) => {
    const preset = e.target.closest('.preset-card') || e.target.closest('.quick-prompt-btn');
    if (preset) {
      const texto = preset.dataset.prompt || preset.querySelector('.preset-text')?.textContent.trim();
      if (texto && inChat) {
        inChat.value = texto;
        inChat.focus();
        inChat.style.height = 'auto';
        inChat.style.height = Math.min(inChat.scrollHeight, 150) + 'px';
        cerrarSidebar();
      }
      // Cada plantilla pide tools de un dominio puntual (la zapata necesita
      // Estructura, no Civil): sin esto quedaba lo que el usuario hubiera
      // dejado elegido antes, el modelo pedía una tool que no estaba en
      // ese perfil, y el pedido fallaba con un mensaje confuso en vez de
      // dibujar. Pasó de verdad probando "Zapata Aislada Z-1" en Civil.
      const perfil = preset.dataset.perfil;
      const selProf = $('#select-profile');
      if (perfil && selProf && selProf.value !== perfil) {
        selProf.value = perfil;
        selProf.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });

  const btnTogglePlan = $('#btn-toggle-plan');
  const layout = $('#app-layout');
  if (btnTogglePlan && layout) {
    btnTogglePlan.onclick = () => {
      const abierto = layout.classList.contains('con-plano');
      if (abierto) layout.classList.remove('con-plano');
      else capturarPlano();
    };
  }

  const btnRefPlan = $('#btn-refresh-plan');
  if (btnRefPlan) btnRefPlan.onclick = () => capturarPlano();

  const btnClosePlan = $('#btn-close-plan');
  if (btnClosePlan && layout) btnClosePlan.onclick = () => layout.classList.remove('con-plano');

  const btnZoomIn = $('#btn-zoom-in');
  const btnZoomOut = $('#btn-zoom-out');
  const btnZoomReset = $('#btn-zoom-reset');
  const btnDownPlan = $('#btn-download-plan');
  if (btnZoomIn) btnZoomIn.onclick = () => actualizarZoom(0.25);
  if (btnZoomOut) btnZoomOut.onclick = () => actualizarZoom(-0.25);
  if (btnZoomReset) btnZoomReset.onclick = () => actualizarZoom(0);
  if (btnDownPlan) btnDownPlan.onclick = descargarCaptura;

  document.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'btn-initial-capture') {
      capturarPlano();
    }
  });

  // Modal / Wizard
  $$('[data-wizard-goto]').forEach(b => {
    b.onclick = () => irPasoWizard(+b.dataset.wizardGoto);
  });
  const btnWizSkip = $('#btn-wizard-skip');
  const btnWizFinish = $('#btn-wizard-finish');
  const btnCloseWiz = $('#btn-close-wizard');
  const btnWizSave = $('#btn-wizard-save-key');
  const btnWizRecheck = $('#btn-wizard-recheck');
  const btnOpenSettings = $('#btn-open-settings');

  if (btnWizSkip) btnWizSkip.onclick = cerrarWizard;
  if (btnWizFinish) btnWizFinish.onclick = cerrarWizard;
  if (btnCloseWiz) btnCloseWiz.onclick = cerrarWizard;
  if (btnWizSave) {
    btnWizSave.onclick = async () => {
      const inWKey = $('#wizard-api-key');
      const k = inWKey ? inWKey.value.trim() : '';
      if (k) {
        await guardarClave(k);
        if (inWKey) inWKey.value = '';
      }
      irPasoWizard(2);
    };
  }
  if (btnWizRecheck) btnWizRecheck.onclick = ejecutarDiagnosticos;
  if (btnOpenSettings) btnOpenSettings.onclick = () => abrirWizard(0);
}

// Iniciar cuando el DOM esté listo
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
