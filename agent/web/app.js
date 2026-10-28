/**
 * AutoCAD IA — Lógica de Aplicación Frontend
 * Inicialización segura y comunicación SSE con el agente
 */

// Dentro de AutoCAD (comando MCPCHAT) el servidor marca <html class="en-autocad">: ya se está viendo el dibujo
// en AutoCAD y la conexión con el plugin es un hecho, así que no hay visor del plano ni chequeo de conexión.
// Todo lo demás —modelos, claves, perfiles de tools, presets, costo, entregables— es lo mismo que en el navegador.
const EN_AUTOCAD = document.documentElement.classList.contains('en-autocad');

let AppState = {
  servidor: null,
  trabajando: false,
  autoPlano: !EN_AUTOCAD,
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
  costoPedido: 0,         // US$ del pedido en curso (último 'uso')
  costoSesion: 0,         // US$ acumulado de los pedidos ya terminados
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
  if (local === null) return porDefecto;
  // Si el default es un objeto, lo guardado tiene que serlo también.
  if (porDefecto !== null && typeof porDefecto === 'object') {
    try {
      const v = JSON.parse(local);
      return v && typeof v === 'object' ? v : porDefecto;
    } catch { return porDefecto; }
  }
  return local;
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
  // Los objetos (precios, presets, modelos) van como JSON: setItem de un
  // objeto guardaba "[object Object]" y al leerlo de vuelta se rompía.
  try {
    localStorage.setItem('autocad_ia_' + clave,
      typeof valor === 'object' && valor !== null ? JSON.stringify(valor) : valor);
  } catch {}
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
  if (EN_AUTOCAD) return;
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
      badge.title = datos.detalle || 'Abre AutoCAD con el plugin cargado.';
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
// Entregables: lo que el agente dejó en la carpeta de entregables (PDF,
// catálogo de conceptos .xlsx, CSV), listo para bajar desde el panel.
async function actualizarEntregables() {
  const cont = document.getElementById('lista-entregables');
  if (!cont) return;
  try {
    const res = await fetch('/api/entregables');
    if (!res.ok) return;
    const { archivos } = await res.json();
    if (!archivos || !archivos.length) return;
    cont.innerHTML = archivos.map(a => {
      const kb = a.bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(a.bytes / 1024))} KB`
        : `${(a.bytes / 1024 / 1024).toFixed(1)} MB`;
      const url = '/entregables/' + encodeURIComponent(a.nombre);
      return `<a class="entregable" href="${url}" download="${escaparHtml(a.nombre)}">` +
             `<span>${escaparHtml(a.nombre)}</span><small>${kb}</small></a>`;
    }).join('');
  } catch {}
}

// ==========================================================================
// LÁMINAS, REVISIÓN E HISTORIAL
// ==========================================================================
function laminaElegida() {
  const sel = document.getElementById('select-layout');
  return sel && sel.value !== 'Model' ? sel.value : null;
}

// Las láminas (layouts) del dibujo, para verlas en el visor tal como se
// imprimen: el espacio modelo no es el entregable.
async function cargarLaminas() {
  const sel = document.getElementById('select-layout');
  if (!sel) return;
  try {
    const res = await fetch('/api/layouts');
    if (!res.ok) return;
    const { layouts } = await res.json();
    const actual = sel.value;
    sel.innerHTML = '<option value="Model">Modelo</option>' +
      (layouts || []).map(l => `<option value="${escaparHtml(l)}">${escaparHtml(l)}</option>`).join('');
    if ([...sel.options].some(o => o.value === actual)) sel.value = actual;
  } catch {}
}

// check_all directo, sin pasar por el modelo: no gasta tokens y en segundos
// dice si el plano tiene problemas (cotas encimadas, muros al aire, dibujo
// fuera del cajón, xrefs rotos…).
async function revisarPlano() {
  const btn = document.getElementById('btn-revisar');
  if (btn) btn.disabled = true;
  limpiarVacio();
  agregarAvisoChat('Revisando el plano (check_all, sin gastar tokens)…');
  try {
    const res = await fetch('/api/revisar', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const r = await res.json();
    if (!res.ok) {
      agregarAvisoChat(r.error || 'No se pudo revisar el plano.');
      return;
    }
    const cont = $('#chat-messages');
    const div = document.createElement('div');
    div.className = 'revision-card ' + (r.ok ? 'revision-ok' : 'revision-mal');
    const filas = (r.problems || []).map(p => `
      <li><b>${escaparHtml(p.check || '')}</b> — ${escaparHtml(p.problem || '')}
      ${p.fix ? `<br><small>→ ${escaparHtml(p.fix)}</small>` : ''}</li>`).join('');
    div.innerHTML = r.ok
      ? `<div class="revision-titulo">✓ Plano sin problemas</div>
         <small>Revisado: ${escaparHtml((r.checks || []).join(', '))}</small>`
      : `<div class="revision-titulo">✕ ${r.count} problema(s) en el plano</div>
         <ul>${filas}</ul>
         <button class="btn btn-sm btn-primary revision-corregir">Pedirle al agente que los corrija</button>`;
    cont.appendChild(div);
    const corregir = div.querySelector('.revision-corregir');
    if (corregir) corregir.onclick = () => {
      const inChat = $('#chat-input');
      if (inChat) {
        inChat.value = 'Corre check_all y corrige los problemas que encuentre, uno por uno, sin rehacer el plano entero.';
        inChat.focus();
      }
    };
    scrollAbajo();
  } catch (e) {
    agregarAvisoChat('No se pudo revisar el plano: ' + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// La conversación sobrevive a recargar la página y a reiniciar el panel:
// el servidor la guarda y acá se vuelve a pintar tal como se vio.
async function restaurarHistorial() {
  try {
    const res = await fetch('/api/historial');
    if (!res.ok) return;
    const { eventos } = await res.json();
    if (!eventos || !eventos.length) return;
    limpiarVacio();
    for (const ev of eventos) {
      if (ev.tipo === 'usuario') {
        agregarBurbuja('Tú', ev.texto || '(imagen adjunta)', true);
      } else {
        despacharEvento(ev);
      }
    }
    agregarAvisoChat('Conversación anterior restaurada. «Nueva Sesión» la borra.');
  } catch {}
}

// ==========================================================================
// COSTO Y PRESETS
// ==========================================================================
AppState.preciosPublicados = {};

function claveModelo() {
  const p = getProveedorActual();
  const inModel = $('#input-model');
  return `${p.id}:${inModel ? inModel.value.trim() : ''}`;
}

function precioManual() {
  const e = parseFloat(($('#input-precio-entrada') || {}).value);
  const s = parseFloat(($('#input-precio-salida') || {}).value);
  if (!(e > 0) && !(s > 0)) return null;
  return { entrada: e || 0, salida: s || 0 };
}

// El precio guardado para este modelo (el que escribió el usuario) o el
// publicado por el proveedor al listar; si no hay, quedan en "auto" y el
// servidor usa el publicado si lo conoce.
function cargarPrecioDelModelo() {
  const guardados = pref('precios', {}) || {};
  const pr = guardados[claveModelo()] || AppState.preciosPublicados[claveModelo()] || null;
  const inE = $('#input-precio-entrada'), inS = $('#input-precio-salida');
  if (inE) inE.value = pr ? pr.entrada : '';
  if (inS) inS.value = pr ? pr.salida : '';
}

function guardarPrecioDelModelo() {
  const guardados = { ...(pref('precios', {}) || {}) };
  const pr = precioManual();
  if (pr) guardados[claveModelo()] = pr; else delete guardados[claveModelo()];
  guardarPref('precios', guardados);
}

function pintarCosto() {
  const el = $('#total-costo');
  if (!el) return;
  const total = AppState.costoSesion + AppState.costoPedido;
  el.textContent = total > 0
    ? ` · ≈ US$${total < 0.01 ? total.toFixed(4) : total.toFixed(2)}`
    : '';
  el.title = `Este pedido: US$${AppState.costoPedido.toFixed(4)} · ` +
             `sesión: US$${total.toFixed(4)} (con el precio por millón de tokens del panel)`;
}

// Presets: proveedor, modelo, perfil, temperatura, reglas, tope y un
// contexto fijo del proyecto, guardados con nombre para no reconfigurar
// todo cada vez que se cambia de tipo de trabajo.
function presets() { return pref('presets', {}) || {}; }

function pintarPresets(elegido = '') {
  const sel = $('#select-preset');
  if (!sel) return;
  sel.innerHTML = '<option value="">— Sin preset —</option>' +
    Object.keys(presets()).sort().map(n =>
      `<option value="${escaparHtml(n)}">${escaparHtml(n)}</option>`).join('');
  sel.value = elegido;
}

function guardarPresetActual() {
  const nombre = (prompt('Nombre del preset (p.ej. "Vivienda Oaxaca 1:75")') || '').trim();
  if (!nombre) return;
  const inModel = $('#input-model'), selProf = $('#select-profile');
  const chk = $('#check-rules'), inTemp = $('#input-temp');
  const todos = { ...presets() };
  todos[nombre] = {
    proveedor: getProveedorActual().id,
    modelo: inModel ? inModel.value.trim() : '',
    perfil: selProf ? selProf.value : 'arquitectura',
    temperatura: inTemp ? parseFloat(inTemp.value) : 0.2,
    conReglas: chk ? chk.checked : true,
    topeUSD: parseFloat(($('#input-tope') || {}).value) || 0,
    contexto: (($('#input-contexto') || {}).value || '').trim(),
  };
  guardarPref('presets', todos);
  pintarPresets(nombre);
  showToast(`Preset "${nombre}" guardado`, 'success');
}

function aplicarPreset(nombre) {
  const pr = presets()[nombre];
  if (!pr) return;
  const selProv = $('#select-provider');
  if (selProv && pr.proveedor && [...selProv.options].some(o => o.value === pr.proveedor)) {
    selProv.value = pr.proveedor;
    if (selProv.onchange) selProv.onchange();
  }
  const inModel = $('#input-model');
  if (inModel && pr.modelo) { inModel.value = pr.modelo; guardarModeloDe(pr.proveedor, pr.modelo); }
  const selProf = $('#select-profile');
  if (selProf && pr.perfil) { selProf.value = pr.perfil; guardarPref('perfil', pr.perfil); }
  const inTemp = $('#input-temp');
  if (inTemp && pr.temperatura !== undefined) {
    inTemp.value = pr.temperatura;
    const salida = $('#temp-val');
    if (salida) salida.textContent = parseFloat(pr.temperatura).toFixed(1);
  }
  const chk = $('#check-rules');
  if (chk && pr.conReglas !== undefined) chk.checked = !!pr.conReglas;
  const inTope = $('#input-tope');
  if (inTope) inTope.value = pr.topeUSD || '';
  const inCtx = $('#input-contexto');
  if (inCtx) inCtx.value = pr.contexto || '';
  cargarPrecioDelModelo();
  actualizarSubtitulo();
  showToast(`Preset "${nombre}" aplicado. El contexto entra desde la próxima Nueva Sesión.`, 'info');
}

function borrarPreset() {
  const sel = $('#select-preset');
  if (!sel || !sel.value) return showToast('Elige un preset primero', 'error');
  const todos = { ...presets() };
  delete todos[sel.value];
  guardarPref('presets', todos);
  pintarPresets('');
}

// Estándar de oficina: el panel lo lee y lo guarda en el MISMO archivo
// que usa check_all, validado con las mismas reglas.
async function cargarEstandar() {
  const ta = $('#input-estandar');
  if (!ta) return;
  try {
    const r = await (await fetch('/api/estandar')).json();
    ta.value = JSON.stringify(r.estandar, null, 2);
    if (r.error) showToast(r.error, 'error');
  } catch {}
}

async function guardarEstandar() {
  const ta = $('#input-estandar');
  if (!ta) return;
  let obj;
  try { obj = JSON.parse(ta.value); }
  catch (e) { return showToast('El JSON no es válido: ' + e.message, 'error'); }
  const res = await fetch('/api/estandar', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ estandar: obj }) });
  const r = await res.json();
  if (!res.ok) return showToast(r.error || 'No se pudo guardar', 'error');
  showToast('Estándar guardado: «Revisar plano» ya lo aplica', 'success');
}

function conectarCostoYPresets() {
  cargarEstandar();
  const btnEst = $('#btn-guardar-estandar');
  if (btnEst) btnEst.onclick = guardarEstandar;
  const tope = pref('topeUSD');
  const inTope = $('#input-tope');
  if (inTope && tope) inTope.value = tope;
  if (inTope) inTope.onchange = () => guardarPref('topeUSD', parseFloat(inTope.value) || 0);
  for (const id of ['#input-precio-entrada', '#input-precio-salida']) {
    const el = $(id);
    if (el) el.onchange = guardarPrecioDelModelo;
  }
  const inModel = $('#input-model');
  if (inModel) inModel.addEventListener('change', cargarPrecioDelModelo);
  cargarPrecioDelModelo();
  pintarPresets('');
  const sel = $('#select-preset');
  if (sel) sel.onchange = () => sel.value && aplicarPreset(sel.value);
  const btnG = $('#btn-preset-guardar');
  if (btnG) btnG.onclick = guardarPresetActual;
  const btnB = $('#btn-preset-borrar');
  if (btnB) btnB.onclick = borrarPreset;
}

// Chromium 77 (el navegador embebido de AutoCAD 2022) acepta `gap` solo en grid: en flexbox lo ignora y todo queda
// pegado. Si no se soporta, por cada regla del CSS con `gap` que se use en un contenedor flex se agrega su
// equivalente con margen entre hijos (`> * + *`). Es CSS generado una vez: sirve también para lo que se agregue luego.
function compatFlexGap() {
  const prueba = document.createElement('div');
  prueba.style.cssText = 'display:flex;flex-direction:column;row-gap:1px;position:absolute;visibility:hidden';
  prueba.appendChild(document.createElement('div'));
  prueba.appendChild(document.createElement('div'));
  document.body.appendChild(prueba);
  const soportado = prueba.scrollHeight === 1;
  document.body.removeChild(prueba);
  if (soportado) return;

  const valores = (r) => {
    const g = (r.style.getPropertyValue('gap') || '').trim().split(/\s+/).filter(Boolean);
    return {
      fila: r.style.getPropertyValue('row-gap') || g[0] || '',
      col: r.style.getPropertyValue('column-gap') || g[1] || g[0] || '',
    };
  };
  const generar = (regla) => {
    const v = valores(regla);
    if (!v.fila && !v.col) return '';
    const sel = regla.selectorText;
    if (!sel || sel.indexOf('::') >= 0) return '';
    let ejemplo = null;
    try { ejemplo = document.querySelector(sel); } catch (e) { return ''; }
    let display = regla.style.getPropertyValue('display');
    let dir = regla.style.getPropertyValue('flex-direction') || 'row';
    if (ejemplo) {
      const cs = getComputedStyle(ejemplo);
      display = cs.display;
      dir = cs.flexDirection;
    }
    if (display.indexOf('flex') < 0) return '';
    const hijos = sel.split(',').map(x => x.trim() + ' > * + *').join(',');
    if (dir.indexOf('column') === 0) return v.fila ? hijos + '{margin-top:' + v.fila + '}\n' : '';
    return v.col ? hijos + '{margin-left:' + v.col + '}\n' : '';
  };
  let css = '';
  for (const hoja of Array.from(document.styleSheets)) {
    let reglas;
    try { reglas = Array.from(hoja.cssRules); } catch (e) { continue; }     // hojas de otro origen (fuentes)
    for (const r of reglas) {
      if (r.type === 1) css += generar(r);
      else if (r.type === 4) {
        const dentro = Array.from(r.cssRules).filter(x => x.type === 1).map(generar).join('');
        if (dentro) css += '@media ' + r.conditionText + '{' + dentro + '}\n';
      }
    }
  }
  const estilo = document.createElement('style');
  estilo.id = 'compat-flex-gap';
  estilo.textContent = css;
  document.head.appendChild(estilo);
}

async function init() {
  try { compatFlexGap(); } catch (e) { console.error('compatFlexGap', e); }
  if (EN_AUTOCAD) {
    const caja = document.getElementById('chat-input');
    if (caja) caja.placeholder = 'Escribe tu instrucción…';
  }
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
    } else if (!(p && p.clave) && !configurado && !(p && p.id === 'local') && !saltar) {
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
  registrarEventosPrimerosPasos();
  abrirPrimerosPasosSiHaceFalta();
  actualizarEstadoAutoCAD();
  actualizarEntregables();
  restaurarHistorial();
  conectarCostoYPresets();
  const btnRevisar = document.getElementById('btn-revisar');
  if (btnRevisar) btnRevisar.onclick = revisarPlano;
  const selLayout = document.getElementById('select-layout');
  if (selLayout) selLayout.onchange = () => capturarPlano();
  const btnPlano = document.getElementById('btn-toggle-plan');
  if (btnPlano) btnPlano.addEventListener('click', cargarLaminas);
  const btnEntregables = document.getElementById('btn-refrescar-entregables');
  if (btnEntregables) btnEntregables.onclick = actualizarEntregables;
  if (!EN_AUTOCAD) setInterval(actualizarEstadoAutoCAD, 15000);
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
  if (prov && ((AppState.servidor && AppState.servidor.proveedores) || []).some(p => p.id === prov)) {
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
  const listos = ((AppState.servidor && AppState.servidor.proveedores) || [])
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
  const id = selProv ? selProv.value : (((((AppState.servidor && AppState.servidor.proveedores) || [])[0]) || {}).id || 'anthropic');
  return ((AppState.servidor && AppState.servidor.proveedores) || []).find(p => p.id === id);
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
      chip.innerHTML = (p.puente || p.vivo) ? `<span>${p.clave}</span>` : `<span>${p.clave} (${modo})</span>`;
    } else if (p.puente) {
      chip.className = 'chip-status warning';
      chip.innerHTML = `<span>${p.detalle}</span>`;
    } else if (p.id === 'local') {
      chip.className = 'chip-status';
      chip.innerHTML = `<span>Local (sin clave)</span>`;
    } else {
      chip.className = 'chip-status warning';
      chip.innerHTML = `<span>Sin clave guardada</span>`;
    }
  }

  // Un puente usa la sesión de la persona: no hay clave que guardar ni borrar.
  ['input-api-key', 'btn-save-key', 'btn-delete-key', 'btn-toggle-key-visibility'].forEach(id => {
    const e = $('#' + id);
    if (e) e.disabled = !!(p.puente || p.vivo);
  });
  const campoClave = $('#input-api-key');
  if (campoClave) campoClave.placeholder = (p.puente || p.vivo) ? 'No necesita clave: usa tu sesión' : 'Nueva API Key';
  aplicarModoVivo(p);

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

    if (!(data.modelos && data.modelos.length)) {
      c.innerHTML = `<div style="font-size:11px;color:var(--text-dim);padding:4px;">No se encontraron modelos.</div>`;
      return;
    }

    const inModel = $('#input-model');
    const modeloActual = inModel ? inModel.value.trim() : '';

    c.innerHTML = data.modelos.map(m => {
      const isOk = m.estado.startsWith('OK');
      const isErr = /bloquead|error|sin respuesta|no/.test(m.estado.toLowerCase());
      const isSelected = m.modelo === modeloActual;
      if (m.precio) AppState.preciosPublicados[`${p.id}:${m.modelo}`] = m.precio;
      const precio = m.precio
        ? `<span class="model-precio" title="US$ por millón de tokens: entrada / salida">$${m.precio.entrada}/${m.precio.salida}</span>`
        : '';
      const ojo = m.imagenes ? '<span title="Acepta imágenes (croquis, fotos)">📷</span>' : '';
      return `
        <div class="model-item ${isOk ? 'ok' : isErr ? 'err' : ''} ${isSelected ? 'selected' : ''}" data-model="${escaparHtml(m.modelo)}" data-buscar="${escaparHtml(m.modelo.toLowerCase())}">
          <span class="model-nombre">${ojo} ${escaparHtml(m.modelo)}</span>
          ${precio}
          <span class="model-badge">${m.estado === '?' ? 'disponible' : escaparHtml(m.estado)}</span>
        </div>
      `;
    }).join('');
    // Con cientos de modelos (OpenRouter tiene más de 450) la lista sin
    // buscador no sirve: se filtra mientras se escribe.
    c.insertAdjacentHTML('afterbegin',
      `<input id="filtro-modelos" class="filtro-modelos" placeholder="Buscar entre ${data.modelos.length} modelos… (p.ej. claude, gpt, 📷)">`);
    const filtro = $('#filtro-modelos');
    if (filtro) filtro.oninput = () => {
      const q = filtro.value.trim().toLowerCase();
      const soloImg = q.includes('📷');
      const texto = q.replace('📷', '').trim();
      $$('.model-item').forEach(el => {
        const ok = (!texto || el.dataset.buscar.includes(texto)) &&
                   (!soloImg || el.querySelector('[title^="Acepta"]'));
        el.style.display = ok ? '' : 'none';
      });
    };

    $$('.model-item').forEach(el => {
      el.onclick = () => {
        const m = el.dataset.model;
        if (inModel) inModel.value = m;
        guardarModeloDe(p.id, m);
        cargarPrecioDelModelo();
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
      body: JSON.stringify({ modelo, proveedor: getProveedorActual().id }),
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
  if (window.__log) window.__log('enviar: texto=' + texto.length + ' trabajando=' + AppState.trabajando + ' proveedor=' + (($('#select-provider') || {}).value || '?'));
  if ((!texto && !AppState.adjuntos.length) || AppState.trabajando) return;

  const p = getProveedorActual();
  if (p && p.vivo) { vivoEnviar(texto); return; }
  if (window.__log) window.__log('enviar: clave=' + !!(p && p.clave) + ' puente=' + !!(p && p.puente));
  if (!p.clave && p.id !== 'local') {
    showToast(p.puente ? p.detalle : `Configura tu API key de ${p.id} antes de continuar`, 'error');
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
        precio: precioManual(),
        topeUSD: parseFloat(($('#input-tope') || {}).value) || 0,
        contexto: (($('#input-contexto') || {}).value || '').trim(),
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (window.__log) window.__log('enviar: el servidor respondió ' + res.status);
      agregarAvisoChat(err.error || `El servidor respondió con código ${res.status}`);
    } else {
      AppState.costoPedido = 0;
      huboDibujo = await procesarSSE(res);
      AppState.costoSesion += AppState.costoPedido;
      AppState.costoPedido = 0;
      pintarCosto();
      actualizarEntregables();
    }
  } catch (err) {
    if (window.__log) window.__log('enviar: se cortó: ' + err.message);
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
    if (typeof ev.costoUSD === 'number') {
      AppState.costoPedido = ev.costoUSD;
      pintarCosto();
    }
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
  if (EN_AUTOCAD) return;      // sin visor: el dibujo se ve en AutoCAD mismo
  const layout = $('#app-layout');
  const canvas = $('#plan-canvas-wrapper');
  if (layout) layout.classList.add('con-plano');
  // Un clic más mientras AutoCAD plotea no lo apura: lo encola detrás y el
  // visor tarda el doble. El servidor también lo frena, pero mejor ni
  // pedirlo.
  if (AppState.capturando) {
    showToast('Ya hay una captura en curso, espera a que termine', 'info');
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
      body: JSON.stringify({ zona, layout: laminaElegida() }),
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
      if (p && p.clave) {
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
  const p = ((AppState.servidor && AppState.servidor.proveedores) || []).find(x => x.id === val);
  const hint = $('#wizard-provider-hint');
  if (!hint || !p) return;

  if (p.vivo) {
    hint.textContent = p.detalle;
  } else if (p.puente) {
    hint.textContent = 'Usa tu Claude Code instalado y su sesión (sin clave de API). ' + (p.clave ? '' : p.detalle);
  } else if (p.id === 'local') {
    hint.textContent = 'Servidor local (LM Studio / Ollama). No requiere clave de API.';
  } else {
    hint.textContent = `Requiere clave de ${p.id.toUpperCase()}` + (p.variable ? ` (o variable ${p.variable}).` : '.');
  }
}

async function ejecutarDiagnosticos() {
  const p = getProveedorActual();

  // 1. Clave
  const okClave = !!(p && p.clave) || !!(p && p.id === 'local');
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

  // 3. AutoCAD MCP (dentro de AutoCAD no hay nada que verificar: la fila ni se muestra)
  if (EN_AUTOCAD) return;
  setDiag('diag-light-cad', null, 'diag-text-cad', 'Verificando plugin de AutoCAD…');
  try {
    // Un ping (~1 s), no una captura: plotear la vista para saber si el
    // plugin responde tardaba ~7 s y dejaba el asistente congelado.
    const res = await fetch('/api/autocad_estado');
    const data = await res.json();
    if (data.conectado) {
      setDiag('diag-light-cad', true, 'diag-text-cad',
        `Plugin ${data.pluginVersion || ''} conectado · ${data.activeDocument || 'sin dibujo abierto'}`);
    } else {
      setDiag('diag-light-cad', false, 'diag-text-cad', (data.detalle || '').slice(0, 70));
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
      if (!c) return showToast('Ingresa una clave', 'error');
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
      const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
      if (files.length) { e.preventDefault(); agregarArchivos(files); }
    });
  }
  const zonaChat = $('#chat-messages');
  if (zonaChat) {
    ['dragover', 'drop'].forEach(ev =>
      zonaChat.addEventListener(ev, (e) => {
        e.preventDefault();
        if (ev === 'drop') {
          agregarArchivos(Array.from((e.dataTransfer && e.dataTransfer.files) || []));
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
      const texto = preset.dataset.prompt || ((preset.querySelector('.preset-text') || {}).textContent || '').trim();
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


// ==========================================================================
// PRIMEROS PASOS: AutoCAD conectado, IA elegida y licencia activada
// ==========================================================================
let ppTimer = null;

function ppMarcar(n, ok, texto) {
  const li = $('#pp-' + n);
  if (!li) return;
  li.classList.toggle('ok', !!ok);
  li.classList.toggle('pend', !ok);
  const est = $('#pp-' + n + '-est');
  if (est) est.textContent = ok ? '✓ Listo' : 'Falta';
  const txt = $('#pp-' + n + '-txt');
  if (txt && texto) txt.textContent = texto;
}

async function refrescarPrimerosPasos() {
  let d;
  try {
    const r = await fetch('/api/primeros_pasos');
    d = await r.json();
  } catch (e) {
    return null;
  }
  const ac = EN_AUTOCAD ? { conectado: true } : (d.autocad || {});
  ppMarcar(1, ac.conectado, ac.conectado
    ? 'AutoCAD está conectado' + ((ac.pluginVersion || ac.version) ? ' (plugin ' + (ac.pluginVersion || ac.version) + ')' : '') + '.'
    : 'No veo AutoCAD. Ábrelo y espera a que cargue el plugin; esto se actualiza solo.');
  const ayuda = $('#pp-1-ayuda');
  if (ayuda) ayuda.hidden = !!ac.conectado;
  const ia = d.ia || {};
  ppMarcar(2, ia.configurada, ia.configurada
    ? 'IA lista: ' + (ia.proveedores || []).join(', ') + '.'
    : 'Elige el proveedor que prefieras y pega tu clave. Se guarda cifrada en tu usuario.');
  const lic = d.licencia || {};
  const sinExigir = !lic.obligatoria;
  ppMarcar(3, lic.valida || sinExigir, lic.valida
    ? (lic.mensaje || 'Licencia activa.')
    : (sinExigir ? 'Esta copia no exige licencia.' : (lic.mensaje || 'Activa tu clave o empieza la prueba gratis de 7 días.')));
  const form = $('#pp-3-form');
  if (form) form.hidden = !!(lic.valida || sinExigir);
  const todo = !!ac.conectado && !!ia.configurada && (lic.valida || sinExigir);
  const ok = $('#btn-start-ok');
  if (ok) ok.textContent = todo ? 'Empezar a dibujar' : 'Continuar de todos modos';
  return { d, todo };
}

function abrirPrimerosPasos() {
  const m = $('#start-modal');
  if (!m) return;
  m.classList.remove('hidden');
  refrescarPrimerosPasos();
  clearInterval(ppTimer);
  ppTimer = setInterval(refrescarPrimerosPasos, 4000);
}

function cerrarPrimerosPasos() {
  const m = $('#start-modal');
  if (m) m.classList.add('hidden');
  clearInterval(ppTimer);
  ppTimer = null;
}

async function ppLicencia(ruta, cuerpo) {
  const err = $('#pp-3-err');
  if (err) err.hidden = true;
  const botones = [$('#btn-pp-activar'), $('#btn-pp-prueba')];
  botones.forEach(b => { if (b) b.disabled = true; });
  try {
    const r = await fetch(ruta, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || 'No se pudo activar.');
    showToast('Licencia activada', 'success');
    await refrescarPrimerosPasos();
  } catch (e) {
    if (err) { err.textContent = e.message; err.hidden = false; }
  } finally {
    botones.forEach(b => { if (b) b.disabled = false; });
  }
}

function registrarEventosPrimerosPasos() {
  const abrir = $('#btn-open-start');
  if (abrir) abrir.onclick = abrirPrimerosPasos;
  const cerrar = $('#btn-close-start');
  if (cerrar) cerrar.onclick = cerrarPrimerosPasos;
  const ok = $('#btn-start-ok');
  if (ok) ok.onclick = cerrarPrimerosPasos;
  const ia = $('#btn-pp-ia');
  if (ia) ia.onclick = () => { cerrarPrimerosPasos(); abrirWizard(0); };
  const act = $('#btn-pp-activar');
  if (act) act.onclick = () => ppLicencia('/api/licencia/activar', { clave: ($('#pp-clave') || {}).value || '' });
  const pru = $('#btn-pp-prueba');
  if (pru) pru.onclick = () => ppLicencia('/api/licencia/prueba');
  const clave = $('#pp-clave');
  if (clave) clave.addEventListener('keydown', e => { if (e.key === 'Enter' && act) act.click(); });
}

async function abrirPrimerosPasosSiHaceFalta() {
  // Al abrir el panel: si la copia exige licencia y no hay una valida, esta pantalla va primero.
  const r = await refrescarPrimerosPasos();
  if (r && r.d && r.d.licencia && r.d.licencia.obligatoria && !r.d.licencia.valida) abrirPrimerosPasos();
}

// ==========================================================================
// MODO «EN VIVO»: un agente con su propia suscripción (Claude Code, OpenCode...) trabaja en SU programa y
// llama a las tools de AutoCAD por MCP. Aquí se ve cada llamada mientras pasa y se le dejan mensajes.
// (Sin ?. ni ??: el navegador embebido de AutoCAD 2022 es Chromium 77.)
// ==========================================================================
const Vivo = { timer: null, posAct: 0, posBan: 0, primera: true, tarjetas: {}, abiertas: 0, hayActividad: false,
               ultima: 0, ocupado: false };

function aplicarModoVivo(p) {
  const vivo = !!(p && p.vivo);
  document.body.classList.toggle('modo-vivo', vivo);
  const caja = $('#chat-input');
  if (caja && vivo) caja.placeholder = 'Mensaje para tu agente…';
  if (caja && !vivo) caja.placeholder = EN_AUTOCAD ? 'Escribe tu instrucción…' : 'Describe lo que quieres que dibuje en AutoCAD…';
  if (vivo) vivoIniciar(); else vivoDetener();
}

function vivoIniciar() {
  if (Vivo.timer) return;
  Vivo.timer = setInterval(vivoSondear, 1200);
  vivoSondear();
  fetch('/api/vivo/info').then(r => r.json()).then(i => {
    const a = $('#vivo-cmd-claude'); if (a) a.textContent = i.claude;
    const b = $('#vivo-cmd-otro'); if (b) b.textContent = 'comando: ' + i.python + '\nargumentos: ' + i.servidor;
  }).catch(() => {});
}

function vivoDetener() {
  clearInterval(Vivo.timer);
  Vivo.timer = null;
}

function vivoEscapar(t) {
  return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function vivoAgregar(el) {
  const lista = $('#vivo-lista');
  if (!lista) return;
  const alFinal = lista.scrollHeight - lista.scrollTop - lista.clientHeight < 60;
  lista.appendChild(el);
  while (lista.childNodes.length > 400) lista.removeChild(lista.firstChild);
  if (alFinal || Vivo.primera) lista.scrollTop = lista.scrollHeight;
}

function vivoResumenArgs(args) {
  let t = '';
  try { t = Object.keys(args || {}).map(k => k + '=' + (typeof args[k] === 'string' ? args[k] : JSON.stringify(args[k]))).join(', '); } catch (e) { t = ''; }
  return t.length > 110 ? t.substring(0, 107) + '…' : t;
}

function vivoPintarEvento(e) {
  Vivo.hayActividad = true;
  Vivo.ultima = Math.max(Vivo.ultima, e.ts || 0);
  if (e.t === 'inicio') {
    const d = document.createElement('div');
    d.className = 'vivo-tool corriendo';
    d.innerHTML = '<div class="vivo-tool-fila"><span class="vivo-ico">⏳</span><span class="vivo-nombre"></span><span class="vivo-ms"></span></div>' +
                  '<div class="vivo-args"></div><div class="vivo-detalle"></div>';
    d.querySelector('.vivo-nombre').textContent = e.tool;
    d.querySelector('.vivo-args').textContent = vivoResumenArgs(e.args);
    d.onclick = () => d.classList.toggle('abierta');
    Vivo.tarjetas[e.id] = d;
    Vivo.abiertas++;
    vivoAgregar(d);
  } else if (e.t === 'fin') {
    let d = Vivo.tarjetas[e.id];
    if (!d) {                       // el inicio quedó fuera de lo que se cargó: se muestra solo el final
      d = document.createElement('div');
      d.className = 'vivo-tool';
      d.innerHTML = '<div class="vivo-tool-fila"><span class="vivo-ico"></span><span class="vivo-nombre"></span><span class="vivo-ms"></span></div><div class="vivo-args"></div><div class="vivo-detalle"></div>';
      d.querySelector('.vivo-nombre').textContent = e.tool;
      d.onclick = () => d.classList.toggle('abierta');
      vivoAgregar(d);
    } else {
      Vivo.abiertas = Math.max(0, Vivo.abiertas - 1);
      delete Vivo.tarjetas[e.id];
    }
    d.classList.remove('corriendo');
    d.classList.add(e.ok ? 'ok' : 'mal');
    d.querySelector('.vivo-ico').textContent = e.ok ? '✓' : '✗';
    d.querySelector('.vivo-ms').textContent = e.ms >= 1000 ? (e.ms / 1000).toFixed(1) + ' s' : (e.ms || 0) + ' ms';
    d.querySelector('.vivo-detalle').textContent = e.texto || '';
  }
}

function vivoPintarMensaje(m) {
  const d = document.createElement('div');
  d.className = 'vivo-msg ' + (m.de === 'usuario' ? 'usuario' : 'claude') + ' tipo-' + (m.tipo || 'info');
  const quien = m.de === 'usuario' ? 'Tú' : 'Tu agente';
  d.innerHTML = '<div class="vivo-quien"></div><div class="vivo-texto"></div>';
  d.querySelector('.vivo-quien').textContent = quien + (m.tipo && m.tipo !== 'info' && m.de !== 'usuario' ? ' · ' + m.tipo : '');
  d.querySelector('.vivo-texto').textContent = m.texto;
  vivoAgregar(d);
}

function vivoEstado() {
  const el = $('#vivo-estado');
  if (!el) return;
  const hace = Vivo.ultima ? Math.round(Date.now() / 1000 - Vivo.ultima) : null;
  if (Vivo.abiertas > 0) {
    el.className = 'vivo-estado trabajando';
    el.textContent = 'Tu agente está trabajando…';
  } else if (hace !== null && hace < 120) {
    el.className = 'vivo-estado';
    el.textContent = 'Tu agente está en espera (última acción hace ' + hace + ' s)';
  } else {
    el.className = 'vivo-estado';
    el.textContent = Vivo.hayActividad ? 'Sin actividad reciente' : 'Esperando a tu agente…';
  }
  const ayuda = $('#vivo-ayuda');
  if (ayuda) ayuda.style.display = Vivo.hayActividad ? 'none' : '';
}

async function vivoSondear() {
  if (Vivo.ocupado) return;
  Vivo.ocupado = true;
  try {
    const limite = Vivo.primera ? 40 : 0;
    const r = await Promise.all([
      fetch('/api/vivo/actividad?desde=' + Vivo.posAct + '&limite=' + limite).then(x => x.json()),
      fetch('/api/vivo/bandeja?desde=' + Vivo.posBan).then(x => x.json()),
    ]);
    Vivo.posAct = r[0].pos;
    Vivo.posBan = r[1].pos;
    const items = r[0].eventos.map(e => ({ ts: e.ts, e: e })).concat(r[1].mensajes.map(m => ({ ts: m.ts, m: m })));
    items.sort((a, b) => a.ts - b.ts);
    items.forEach(it => { if (it.e) vivoPintarEvento(it.e); else vivoPintarMensaje(it.m); });
    Vivo.primera = false;
    vivoEstado();
  } catch (e) {
    const el = $('#vivo-estado');
    if (el) { el.className = 'vivo-estado'; el.textContent = 'Sin conexión con el panel'; }
  } finally {
    Vivo.ocupado = false;
  }
}

async function vivoEnviar(texto) {
  const caja = $('#chat-input');
  if (caja) { caja.value = ''; caja.style.height = 'auto'; }
  try {
    const res = await fetch('/api/vivo/mensaje', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ texto: texto }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); showToast(j.error || 'No se pudo enviar el mensaje', 'error'); return; }
    vivoSondear();
  } catch (e) {
    showToast('No se pudo enviar el mensaje: ' + e.message, 'error');
  }
}

// Iniciar cuando el DOM esté listo
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
