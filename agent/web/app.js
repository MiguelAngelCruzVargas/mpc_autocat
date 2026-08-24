/**
 * AutoCAD IA — Aplicación Web Frontend (Responsiva & Modular)
 */

// Estado Global
const AppState = {
  servidor: null,        // Metadatos de /api/estado
  trabajando: false,     // Ejecución activa del agente
  autoPlano: true,       // Apertura automática del visor al dibujar
  zoomNivel: 1,          // Factor de zoom actual
  planUrlActual: null,   // URL de la última captura
  isPanning: false,      // Estado de arrastre del plano
  panStartX: 0,
  panStartY: 0,
  scrollLeft: 0,
  scrollTop: 0,
};

// Utilidades DOM
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

// Referencias a elementos
const DOM = {
  appLayout: $('#app-layout'),
  appSidebar: $('#app-sidebar'),
  sidebarBackdrop: $('#sidebar-backdrop'),
  btnOpenSidebar: $('#btn-open-sidebar'),
  btnCloseSidebar: $('#btn-close-sidebar'),

  // Chat
  chatMessages: $('#chat-messages'),
  chatInput: $('#chat-input'),
  btnSend: $('#btn-send'),
  btnCancel: $('#btn-cancel'),
  typingIndicator: $('#typing-indicator'),
  tokenCounter: $('#token-counter'),
  totalTokens: $('#total-tokens'),
  totalTurns: $('#total-turns'),
  sessionSubtitle: $('#session-subtitle'),
  connectionStatus: $('#connection-status'),

  // Configuración
  selectProvider: $('#select-provider'),
  keyStatusChip: $('#key-status-chip'),
  inputApiKey: $('#input-api-key'),
  btnToggleKeyVisibility: $('#btn-toggle-key-visibility'),
  btnSaveKey: $('#btn-save-key'),
  btnDeleteKey: $('#btn-delete-key'),
  inputModel: $('#input-model'),
  btnListModels: $('#btn-list-models'),
  btnTestModels: $('#btn-test-models'),
  modelListContainer: $('#model-list-container'),
  inputTemp: $('#input-temp'),
  tempVal: $('#temp-val'),
  selectProfile: $('#select-profile'),
  checkRules: $('#check-rules'),
  btnNewSession: $('#btn-new-session'),
  btnOpenSettings: $('#btn-open-settings'),

  // Visor de plano
  btnTogglePlan: $('#btn-toggle-plan'),
  planViewerPane: $('#plan-viewer-pane'),
  planCanvasWrapper: $('#plan-canvas-wrapper'),
  planFooterInfo: $('#plan-footer-info'),
  planZoomInfo: $('#plan-zoom-info'),
  btnRefreshPlan: $('#btn-refresh-plan'),
  btnClosePlan: $('#btn-close-plan'),
  btnZoomIn: $('#btn-zoom-in'),
  btnZoomOut: $('#btn-zoom-out'),
  btnZoomReset: $('#btn-zoom-reset'),
  btnDownloadPlan: $('#btn-download-plan'),
  btnInitialCapture: $('#btn-initial-capture'),

  // Modal Asistente
  welcomeModal: $('#welcome-modal'),
  btnCloseWizard: $('#btn-close-wizard'),
  wizardProvider: $('#wizard-provider'),
  wizardProviderHint: $('#wizard-provider-hint'),
  wizardApiKey: $('#wizard-api-key'),
  btnToggleWizardKey: $('#btn-toggle-wizard-key'),
  wizardKeyStatusChip: $('#wizard-key-status-chip'),
  btnWizardSkip: $('#btn-wizard-skip'),
  btnWizardSaveKey: $('#btn-wizard-save-key'),
  btnWizardRecheck: $('#btn-wizard-recheck'),
  btnWizardFinish: $('#btn-wizard-finish'),
  toastContainer: $('#toast-container'),
};

// ==========================================================================
// INICIALIZACIÓN
// ==========================================================================
async function init() {
  try {
    const res = await fetch('/api/estado');
    if (!res.ok) throw new Error('No se pudo comunicar con el servidor local');
    AppState.servidor = await res.json();
    
    poblarOpciones();
    cargarConfiguracionGuardada();
    // Si nunca se eligio proveedor pero YA hay uno con clave guardada,
    // arrancar en ese. Sin esto la app abre en el primero alfabetico
    // (anthropic), lo ve sin clave y muestra el asistente a alguien que
    // en realidad ya estaba configurado.
    if (!localStorage.getItem('autocad_ia_proveedor')) {
      const conClave = AppState.servidor.proveedores.find(x => x.clave);
      if (conClave && DOM.selectProvider) {
        DOM.selectProvider.value = conClave.id;
        if (DOM.wizardProvider) DOM.wizardProvider.value = conClave.id;
      }
    }
    marcarProveedorListo();
    renderizarConfiguracion();

    const p = getProveedorActual();
    const configurado = localStorage.getItem('autocad_ia_configurado');
    // ?skip=1 salta el asistente sin marcarlo como configurado: sirve para
    // revisar la interfaz y para volver a abrirlo despues.
    const saltar = new URLSearchParams(location.search).has('skip');
    if (!p?.clave && !configurado && p?.id !== 'local' && !saltar) {
      abrirWizard(0);
    }
  } catch (err) {
    showToast('Error conectando al backend: ' + err.message, 'error');
    if (DOM.connectionStatus) {
      DOM.connectionStatus.className = 'status-badge';
      DOM.connectionStatus.textContent = '● Sin conexión';
    }
  }

  registrarEventos();
}

function poblarOpciones() {
  const { proveedores, perfiles } = AppState.servidor;

  // Los que YA tienen clave van primero y con un candado: son los que se
  // pueden usar ahora mismo. Ordenar alfabético dejaba a 'anthropic'
  // arriba aunque no estuviera configurado, y el que sí lo estaba había
  // que ir a buscarlo en la lista.
  const listos = proveedores.filter(p => p.clave || p.id === 'local');
  const pendientes = proveedores.filter(p => !p.clave && p.id !== 'local');
  const comoOpcion = (p) =>
    `<option value="${p.id}">${p.clave ? '🔒 ' : p.id === 'local' ? '💻 ' : ''}` +
    `${p.id.toUpperCase()}${p.clave ? ' — listo' : ''}</option>`;

  const opsProveedores =
    (listos.length
      ? `<optgroup label="Configurados">${listos.map(comoOpcion).join('')}</optgroup>`
      : '') +
    (pendientes.length
      ? `<optgroup label="Sin clave">${pendientes.map(comoOpcion).join('')}</optgroup>`
      : '');

  DOM.selectProvider.innerHTML = opsProveedores;
  DOM.wizardProvider.innerHTML = opsProveedores;

  DOM.selectProfile.innerHTML = perfiles.map(p =>
    `<option value="${p.id}" ${p.id === 'arquitectura' ? 'selected' : ''}>` +
    `${p.id.charAt(0).toUpperCase() + p.id.slice(1)} (${p.tools} tools)</option>`
  ).join('');
}

function cargarConfiguracionGuardada() {
  const prov = localStorage.getItem('autocad_ia_proveedor');
  if (prov && AppState.servidor.proveedores.some(p => p.id === prov)) {
    DOM.selectProvider.value = prov;
    DOM.wizardProvider.value = prov;
  }
}

function getProveedorActual() {
  return AppState.servidor?.proveedores.find(p => p.id === DOM.selectProvider.value);
}

function renderizarConfiguracion() {
  const p = getProveedorActual();
  if (!p) return;

  localStorage.setItem('autocad_ia_proveedor', p.id);

  if (p.clave) {
    const modo = p.proteccion === 'dpapi' ? 'cifrada' : 'almacenada';
    DOM.keyStatusChip.className = 'chip-status encrypted';
    DOM.keyStatusChip.innerHTML = `🔒 <span>${p.clave} (${modo})</span>`;
  } else if (p.id === 'local') {
    DOM.keyStatusChip.className = 'chip-status';
    DOM.keyStatusChip.innerHTML = `💻 <span>Local (sin clave)</span>`;
  } else {
    DOM.keyStatusChip.className = 'chip-status warning';
    DOM.keyStatusChip.innerHTML = `⚠️ <span>Sin clave guardada</span>`;
  }

  const modeloGuardado = localStorage.getItem('autocad_ia_modelo:' + p.id);
  DOM.inputModel.value = modeloGuardado || p.modeloSugerido;
  DOM.modelListContainer.innerHTML = '';

  marcarProveedorListo();
  actualizarSubtitulo();
}

function marcarProveedorListo() {
  // El borde del selector dice de un vistazo si el proveedor elegido se
  // puede usar ya o le falta la clave.
  const p = getProveedorActual();
  if (!DOM.selectProvider) return;
  DOM.selectProvider.classList.toggle(
    'listo', !!(p && (p.clave || p.id === 'local')));
}

function actualizarSubtitulo() {
  const p = getProveedorActual();
  const m = DOM.inputModel.value.trim() || '(sin modelo)';
  DOM.sessionSubtitle.textContent = `${m} · ${p ? p.id : ''}`;
}

// ==========================================================================
// ACCIONES DE PROVEEDOR Y MODELO
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
    showToast('Clave guardada y protegida', 'success');
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
  DOM.modelListContainer.innerHTML = `
    <div style="font-size:11.5px;color:var(--text-muted);padding:6px;">
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
      DOM.modelListContainer.innerHTML = '';
      showToast(data.error, 'error');
      return;
    }

    if (!data.modelos?.length) {
      DOM.modelListContainer.innerHTML = `
        <div style="font-size:11px;color:var(--text-dim);padding:4px;">No se encontraron modelos.</div>`;
      return;
    }

    const modeloActual = DOM.inputModel.value.trim();
    DOM.modelListContainer.innerHTML = data.modelos.map(m => {
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
        DOM.inputModel.value = m;
        localStorage.setItem('autocad_ia_modelo:' + p.id, m);
        $$('.model-item').forEach(x => x.classList.remove('selected'));
        el.classList.add('selected');
        actualizarSubtitulo();
      };
    });
  } catch (err) {
    DOM.modelListContainer.innerHTML = '';
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

function agregarBurbuja(autor, texto, esUsuario = false) {
  limpiarVacio();
  const row = document.createElement('div');
  row.className = `message-row ${esUsuario ? 'user' : 'assistant'}`;
  row.innerHTML = `
    <div class="message-author">${esUsuario ? 'Tú 👤' : 'AutoCAD IA 🤖'}</div>
    <div class="message-bubble"></div>
  `;
  row.querySelector('.message-bubble').textContent = texto;
  DOM.chatMessages.appendChild(row);
  scrollAbajo();
}

function agregarToolCard(nombre, args, estado = 'running') {
  limpiarVacio();
  const card = document.createElement('div');
  card.className = `tool-card ${estado}`;
  
  let icono = '⚡';
  if (estado === 'success') icono = '✓';
  if (estado === 'error') icono = '✕';

  card.innerHTML = `
    <div class="tool-card-icon">${icono}</div>
    <div class="tool-card-body">
      <div class="tool-card-header">
        <span class="tool-card-name">${nombre}</span>
      </div>
      <div class="tool-card-details"></div>
    </div>
  `;
  card.querySelector('.tool-card-details').textContent = args;
  DOM.chatMessages.appendChild(card);
  scrollAbajo();
}

function agregarAvisoChat(texto) {
  limpiarVacio();
  const notice = document.createElement('div');
  notice.className = 'chat-notice';
  notice.innerHTML = `<span>ℹ️</span> <div>${texto}</div>`;
  DOM.chatMessages.appendChild(notice);
  scrollAbajo();
}

function scrollAbajo() {
  DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight;
}

const REGEX_DIBUJO = /^(create_|draw_|place_|suggest_furniture|dimension_|label_|union_|compose_|delete_|move_|offset_|mirror_|array_|copy_|rotate_|scale_)/;

async function enviarMensaje() {
  const texto = DOM.chatInput.value.trim();
  if (!texto || AppState.trabajando) return;

  const p = getProveedorActual();
  if (!p.clave && p.id !== 'local') {
    showToast(`Configurá tu API key de ${p.id} antes de continuar`, 'error');
    return;
  }

  DOM.chatInput.value = '';
  DOM.chatInput.style.height = 'auto';
  agregarBurbuja('Tú', texto, true);

  AppState.trabajando = true;
  DOM.btnSend.disabled = true;
  DOM.btnCancel.style.display = 'inline-flex';
  DOM.typingIndicator.style.display = 'inline-flex';

  let huboDibujo = false;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mensaje: texto,
        proveedor: p.id,
        modelo: DOM.inputModel.value.trim(),
        perfil: DOM.selectProfile.value,
        conReglas: DOM.checkRules.checked,
        temperatura: parseFloat(DOM.inputTemp.value) || 0.2,
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
    DOM.btnSend.disabled = false;
    DOM.btnCancel.style.display = 'none';
    DOM.typingIndicator.style.display = 'none';

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

  while (true) {
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
        if (despacharEvento(ev)) {
          realizoDibujo = true;
        }
      } catch {}
    }
  }
  return realizoDibujo;
}

function despacharEvento(ev) {
  if (ev.tipo === 'inicio') {
    DOM.sessionSubtitle.textContent = `${ev.modelo} · ${ev.tools} tools`;
  } else if (ev.tipo === 'uso') {
    DOM.tokenCounter.style.display = 'flex';
    DOM.totalTokens.textContent = ev.total.toLocaleString('es');
    DOM.totalTurns.textContent = ev.vueltas;
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
async function capturarPlano(zona = null) {
  DOM.appLayout.classList.add('con-plano');
  DOM.planCanvasWrapper.className = 'viewer-canvas-wrapper empty-canvas';
  DOM.planCanvasWrapper.innerHTML = `
    <div class="typing-dots"><span></span><span></span><span></span></div>
    <div style="font-size:13px;color:var(--text-muted);margin-top:8px;">Capturando vista de AutoCAD…</div>
  `;

  try {
    const res = await fetch('/api/captura', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zona }),
    });
    const data = await res.json();
    if (data.ok) {
      mostrarPlano(data);
    } else {
      DOM.planCanvasWrapper.innerHTML = `
        <div style="color:var(--error);text-align:center;padding:20px;">
          ✕ ${data.error || 'No se pudo obtener la captura.'}
        </div>
      `;
    }
  } catch (err) {
    DOM.planCanvasWrapper.innerHTML = `
      <div style="color:var(--error);padding:20px;">${err.message}</div>
    `;
  }
}

function mostrarPlano(data) {
  AppState.zoomNivel = 1;
  AppState.planUrlActual = data.url;
  DOM.planCanvasWrapper.className = 'viewer-canvas-wrapper';
  DOM.planCanvasWrapper.innerHTML = `
    <img id="plan-image" src="${data.url}" alt="Plano AutoCAD" draggable="false">
  `;

  actualizarZoom(0);

  const ext = data.extension;
  if (ext && !ext.isEmpty) {
    const w = (ext.width || 0).toFixed(2);
    const h = (ext.height || 0).toFixed(2);
    const ent = ext.entities || 0;
    DOM.planFooterInfo.textContent = `${w} × ${h} m · ${ent} entidades`;
  } else {
    DOM.planFooterInfo.textContent = 'Vista general';
  }
}

function actualizarZoom(delta) {
  if (delta === 0) AppState.zoomNivel = 1;
  else AppState.zoomNivel = Math.max(0.4, Math.min(5, AppState.zoomNivel + delta));

  const img = $('#plan-image');
  if (img) img.style.transform = `scale(${AppState.zoomNivel})`;
  DOM.planZoomInfo.textContent = `${Math.round(AppState.zoomNivel * 100)}%`;
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
  DOM.welcomeModal.classList.remove('hidden');
  irPasoWizard(paso);
}

function cerrarWizard() {
  localStorage.setItem('autocad_ia_configurado', '1');
  DOM.welcomeModal.classList.add('hidden');
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
    if (p.clave) {
      DOM.wizardKeyStatusChip.className = 'chip-status encrypted';
      DOM.wizardKeyStatusChip.innerHTML = `🔒 Ya configurada (${p.clave})`;
    } else {
      DOM.wizardKeyStatusChip.className = 'chip-status';
      DOM.wizardKeyStatusChip.textContent = 'Sin clave guardada';
    }
  } else if (paso === 2) {
    ejecutarDiagnosticos();
  }
}

function actualizarHintWizard() {
  const p = AppState.servidor.proveedores.find(x => x.id === DOM.wizardProvider.value);
  if (!p) return;
  if (p.id === 'local') {
    DOM.wizardProviderHint.textContent = 'Servidor local (LM Studio / Ollama). No requiere clave de API.';
  } else {
    DOM.wizardProviderHint.textContent = `Requiere clave de ${p.id.toUpperCase()}` + (p.variable ? ` (o variable ${p.variable}).` : '.');
  }
}

async function ejecutarDiagnosticos() {
  const p = getProveedorActual();

  // 1. Clave
  const okClave = !!p.clave || p.id === 'local';
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
  el.className = 'status-light ' + (estado === null ? 'loading' : estado ? 'ok' : 'error');
  $('#' + textId).textContent = desc;
}

// ==========================================================================
// TOAST & EVENTOS
// ==========================================================================
function showToast(msg, tipo = 'info') {
  const t = document.createElement('div');
  t.className = `toast ${tipo}`;
  const icon = tipo === 'success' ? '✓' : tipo === 'error' ? '✕' : 'ℹ';
  t.innerHTML = `<span>${icon}</span> <span>${msg}</span>`;
  DOM.toastContainer.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transform = 'translateY(8px)';
    setTimeout(() => t.remove(), 250);
  }, 3500);
}

function registrarEventos() {
  // Toggle Sidebar Móvil
  const abrirSidebar = () => {
    DOM.appSidebar.classList.add('mobile-open');
    DOM.sidebarBackdrop.classList.add('active');
  };
  const cerrarSidebar = () => {
    DOM.appSidebar.classList.remove('mobile-open');
    DOM.sidebarBackdrop.classList.remove('active');
  };
  DOM.btnOpenSidebar.onclick = abrirSidebar;
  DOM.btnCloseSidebar.onclick = cerrarSidebar;
  DOM.sidebarBackdrop.onclick = cerrarSidebar;

  // Acordeones colapsables en sidebar
  $$('[data-toggle="accordion"]').forEach(header => {
    header.onclick = () => {
      header.closest('.accordion-item').classList.toggle('open');
    };
  });

  // Slider de temperatura
  DOM.inputTemp.oninput = () => {
    DOM.tempVal.textContent = DOM.inputTemp.value;
  };

  // Cambios de proveedor
  DOM.selectProvider.onchange = () => {
    DOM.wizardProvider.value = DOM.selectProvider.value;
    renderizarConfiguracion();
  };
  DOM.wizardProvider.onchange = () => {
    DOM.selectProvider.value = DOM.wizardProvider.value;
    renderizarConfiguracion();
    actualizarHintWizard();
  };

  // Claves
  DOM.btnSaveKey.onclick = async () => {
    const c = DOM.inputApiKey.value.trim();
    if (!c) return showToast('Ingresá una clave', 'error');
    if (await guardarClave(c)) DOM.inputApiKey.value = '';
  };
  DOM.btnDeleteKey.onclick = borrarClave;
  DOM.btnToggleKeyVisibility.onclick = () => {
    const isPass = DOM.inputApiKey.type === 'password';
    DOM.inputApiKey.type = isPass ? 'text' : 'password';
    DOM.btnToggleKeyVisibility.textContent = isPass ? '🙈' : '👁️';
  };
  DOM.btnToggleWizardKey.onclick = () => {
    const isPass = DOM.wizardApiKey.type === 'password';
    DOM.wizardApiKey.type = isPass ? 'text' : 'password';
    DOM.btnToggleWizardKey.textContent = isPass ? '🙈' : '👁️';
  };

  // Modelos
  DOM.inputModel.oninput = () => {
    const p = getProveedorActual();
    localStorage.setItem('autocad_ia_modelo:' + p.id, DOM.inputModel.value);
    actualizarSubtitulo();
  };
  DOM.btnListModels.onclick = () => listarModelos(false);
  DOM.btnTestModels.onclick = () => listarModelos(true);

  // Sesión
  DOM.btnNewSession.onclick = async () => {
    if (!confirm('¿Reiniciar sesión? El agente olvidará los comandos previos.')) return;
    try {
      await fetch('/api/reset', { method: 'POST' });
      DOM.chatMessages.innerHTML = '';
      DOM.tokenCounter.style.display = 'none';
      showToast('Nueva sesión iniciada', 'success');
      agregarAvisoChat('Sesión reiniciada. Listo para un nuevo plano en AutoCAD.');
    } catch (e) {
      showToast('Error: ' + e.message, 'error');
    }
  };

  // Envío de chat
  DOM.btnSend.onclick = enviarMensaje;
  DOM.chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      enviarMensaje();
    }
  });
  DOM.chatInput.addEventListener('input', () => {
    DOM.chatInput.style.height = 'auto';
    DOM.chatInput.style.height = Math.min(DOM.chatInput.scrollHeight, 160) + 'px';
  });

  // Cancelar agente
  DOM.btnCancel.onclick = async () => {
    try {
      await fetch('/api/cancelar', { method: 'POST' });
      showToast('Cancelando tras la herramienta actual…', 'info');
    } catch (e) {
      showToast('Error: ' + e.message, 'error');
    }
  };

  // Clic en sugerencias y plantillas de prompts
  document.addEventListener('click', (e) => {
    const preset = e.target.closest('.preset-card') || e.target.closest('.quick-prompt-btn');
    if (preset) {
      const texto = preset.dataset.prompt || preset.querySelector('.preset-text')?.textContent.trim();
      if (texto) {
        DOM.chatInput.value = texto;
        DOM.chatInput.focus();
        DOM.chatInput.style.height = 'auto';
        DOM.chatInput.style.height = Math.min(DOM.chatInput.scrollHeight, 160) + 'px';
        cerrarSidebar();
      }
    }
  });

  // Visor de plano
  DOM.btnTogglePlan.onclick = () => {
    const abierto = DOM.appLayout.classList.contains('con-plano');
    if (abierto) DOM.appLayout.classList.remove('con-plano');
    else capturarPlano();
  };
  DOM.btnRefreshPlan.onclick = () => capturarPlano();
  DOM.btnClosePlan.onclick = () => DOM.appLayout.classList.remove('con-plano');
  DOM.btnZoomIn.onclick = () => actualizarZoom(0.25);
  DOM.btnZoomOut.onclick = () => actualizarZoom(-0.25);
  DOM.btnZoomReset.onclick = () => actualizarZoom(0);
  DOM.btnDownloadPlan.onclick = descargarCaptura;

  document.addEventListener('click', (e) => {
    if (e.target && e.target.id === 'btn-initial-capture') {
      capturarPlano();
    }
  });

  // Arrastre con mouse (Pan) en el visor
  DOM.planCanvasWrapper.addEventListener('mousedown', (e) => {
    if (e.target.id !== 'plan-image') return;
    AppState.isPanning = true;
    AppState.panStartX = e.pageX - DOM.planCanvasWrapper.offsetLeft;
    AppState.panStartY = e.pageY - DOM.planCanvasWrapper.offsetTop;
    AppState.scrollLeft = DOM.planCanvasWrapper.scrollLeft;
    AppState.scrollTop = DOM.planCanvasWrapper.scrollTop;
  });
  window.addEventListener('mouseup', () => AppState.isPanning = false);
  DOM.planCanvasWrapper.addEventListener('mousemove', (e) => {
    if (!AppState.isPanning) return;
    e.preventDefault();
    const x = e.pageX - DOM.planCanvasWrapper.offsetLeft;
    const y = e.pageY - DOM.planCanvasWrapper.offsetTop;
    DOM.planCanvasWrapper.scrollLeft = AppState.scrollLeft - (x - AppState.panStartX);
    DOM.planCanvasWrapper.scrollTop = AppState.scrollTop - (y - AppState.panStartY);
  });

  // Wizard
  $$('[data-wizard-goto]').forEach(b => {
    b.onclick = () => irPasoWizard(+b.dataset.wizardGoto);
  });
  DOM.btnWizardSkip.onclick = cerrarWizard;
  DOM.btnWizardFinish.onclick = cerrarWizard;
  DOM.btnCloseWizard.onclick = cerrarWizard;
  DOM.btnWizardSaveKey.onclick = async () => {
    const k = DOM.wizardApiKey.value.trim();
    if (k) {
      await guardarClave(k);
      DOM.wizardApiKey.value = '';
    }
    irPasoWizard(2);
  };
  DOM.btnWizardRecheck.onclick = ejecutarDiagnosticos;
  DOM.btnOpenSettings.onclick = () => abrirWizard(0);
}

document.addEventListener('DOMContentLoaded', init);
