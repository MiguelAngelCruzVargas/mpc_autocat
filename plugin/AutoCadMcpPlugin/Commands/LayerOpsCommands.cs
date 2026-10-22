using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Herramientas de capas que AutoCAD trae como comandos (LAYMRG, LAYDEL, LAYISO/LAYUNISO, estados de
    /// capa) y que acá se resuelven con la API administrada, en UNA transacción: o se hace todo o no
    /// queda nada. La lista de lo que existe sale de leer AcLayerTools (descompilado): ahí se ve que
    /// LAYISO guarda el estado previo con el nombre «_LAYISO_STATE» y que cada herramienta recorre los
    /// bloques además del espacio activo.
    ///
    /// Los ESTADOS DE CAPA son los del administrador nativo (Database.LayerStateManager, que está en
    /// acdbmgd): quedan en el dibujo y aparecen en el cuadro «Estados de capa» de AutoCAD.
    /// </summary>
    public static class LayerOpsCommands
    {
        private const string EstadoAislar = "_MCP_ISOLATE";
        private static readonly string[] Protegidas = { "0", "Defpoints" };

        // ------------------------------------------------------------ utilidades

        private static string Texto(JsonObject pars, string clave)
        {
            string v = pars[clave]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(v)) throw new ArgumentException("Falta '" + clave + "'.");
            return v;
        }

        private static bool EsProtegida(string nombre)
        {
            return Protegidas.Any(p => p.Equals(nombre, StringComparison.OrdinalIgnoreCase));
        }

        private static void ValidarNombreEstado(string nombre)
        {
            DatabaseObjectsCommands.ValidarNombre(nombre);
            if (nombre.Length > 100) throw new ArgumentException("El nombre del estado no puede pasar de 100 caracteres.");
        }

        private static ObjectId CapaId(Database db, Transaction tr, string nombre, string cual)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (!lt.Has(nombre)) throw new ArgumentException("No hay una capa llamada '" + nombre + "' (" + cual + ").");
            return lt[nombre];
        }

        /// <summary>Todos los bloques propios del dibujo (modelo, láminas y definiciones), sin los xrefs: lo de un
        /// xref no se puede tocar desde acá.</summary>
        private static List<ObjectId> BloquesPropios(Database db, Transaction tr)
        {
            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var lista = new List<ObjectId>();
            foreach (ObjectId id in bt)
            {
                var btr = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                if (btr.IsFromExternalReference || btr.IsFromOverlayReference) continue;
                lista.Add(id);
            }
            return lista;
        }

        // ============================================================ FUSIONAR CAPAS (LAYMRG)

        /// <summary>params: sources[] (capas a fusionar), target (capa que las absorbe). Todo lo que estaba en
        /// las capas de origen —en el modelo, las láminas y dentro de las definiciones de bloque— pasa a la
        /// destino, y las de origen se borran. Si la capa actual es una de origen, la actual pasa a ser la destino.</summary>
        public static JsonObject Merge(Document doc, JsonObject pars)
        {
            var fuentes = (pars["sources"] as JsonArray ?? throw new ArgumentException("Falta 'sources' (lista de capas)."))
                .Select(n => n.GetValue<string>()).ToList();
            if (fuentes.Count == 0) throw new ArgumentException("'sources' necesita al menos una capa.");
            if (fuentes.Count > 200) throw new ArgumentException("Máximo 200 capas por llamada.");
            string destino = Texto(pars, "target");
            var db = doc.Database;
            var movidasPorCapa = new JsonObject();
            var borradas = new JsonArray();
            int movidas = 0;
            bool cambioActual = false;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                    if (!lt.Has(destino)) throw new ArgumentException("La capa destino '" + destino + "' no existe.");
                    var idDestino = lt[destino];
                    var nombresReales = new List<string>();
                    var idsFuente = new Dictionary<ObjectId, string>();
                    foreach (var f in fuentes)
                    {
                        if (f.IndexOf('|') >= 0) throw new ArgumentException("'" + f + "' es una capa de xref: no se fusiona.");
                        if (EsProtegida(f)) throw new ArgumentException("La capa '" + f + "' es del sistema: no se puede fusionar.");
                        if (f.Equals(destino, StringComparison.OrdinalIgnoreCase))
                            throw new ArgumentException("El destino '" + destino + "' no puede estar también entre los orígenes.");
                        if (!lt.Has(f)) throw new ArgumentException("No hay una capa llamada '" + f + "'.");
                        var id = lt[f];
                        var rec = (LayerTableRecord)tr.GetObject(id, OpenMode.ForRead);
                        idsFuente[id] = rec.Name;
                    }
                    var porNombre = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    foreach (var kv in idsFuente) { porNombre[kv.Value] = kv.Value; movidasPorCapa[kv.Value] = 0; }
                    string nombreDestino = ((LayerTableRecord)tr.GetObject(idDestino, OpenMode.ForRead)).Name;

                    if (idsFuente.ContainsKey(db.Clayer))
                    {
                        db.Clayer = idDestino;
                        cambioActual = true;
                    }

                    foreach (var bid in BloquesPropios(db, tr))
                    {
                        var btr = (BlockTableRecord)tr.GetObject(bid, OpenMode.ForRead);
                        foreach (ObjectId eid in btr)
                        {
                            var ent = tr.GetObject(eid, OpenMode.ForRead) as Entity;
                            if (ent == null || !porNombre.TryGetValue(ent.Layer, out string origen)) continue;
                            ent.UpgradeOpen();
                            ent.Layer = nombreDestino;
                            movidas++;
                            movidasPorCapa[origen] = movidasPorCapa[origen].GetValue<int>() + 1;
                        }
                    }

                    var candidatos = new ObjectIdCollection();
                    foreach (var id in idsFuente.Keys) candidatos.Add(id);
                    db.Purge(candidatos);
                    foreach (var id in idsFuente.Keys)
                    {
                        if (!candidatos.Contains(id))
                            throw new InvalidOperationException("La capa '" + idsFuente[id] + "' sigue en uso después de pasar sus objetos (¿filtros, " +
                                "congelado en viewports u otra referencia?). No se hizo ningún cambio.");
                        var w = tr.GetObject(id, OpenMode.ForWrite);
                        w.Erase(true);
                        borradas.Add(idsFuente[id]);
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó la fusión (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject
            {
                ["target"] = destino, ["merged"] = borradas, ["objectsMoved"] = movidas,
                ["movedPerLayer"] = movidasPorCapa, ["currentLayerChanged"] = cambioActual
            };
        }

        // ============================================================ BORRAR CAPA CON SUS OBJETOS (LAYDEL)

        /// <summary>params: name, confirm (obligatorio en true). Borra TODOS los objetos de la capa —modelo, láminas
        /// y definiciones de bloque— y la capa. Es destructivo: sin confirm=true se limita a contar lo que borraría.</summary>
        public static JsonObject DeleteWithObjects(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            bool confirmar = pars["confirm"]?.GetValue<bool>() ?? false;
            var db = doc.Database;
            var porTipo = new SortedDictionary<string, int>();
            int total = 0;
            string real;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    if (nombre.IndexOf('|') >= 0) throw new ArgumentException("'" + nombre + "' es una capa de xref.");
                    if (EsProtegida(nombre)) throw new ArgumentException("La capa '" + nombre + "' es del sistema: no se borra.");
                    var id = CapaId(db, tr, nombre, "name");
                    real = ((LayerTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name;
                    if (id == db.Clayer)
                        throw new InvalidOperationException("'" + real + "' es la capa ACTUAL: poné otra con set_current antes de borrarla.");
                    var aBorrar = new List<ObjectId>();
                    foreach (var bid in BloquesPropios(db, tr))
                    {
                        var btr = (BlockTableRecord)tr.GetObject(bid, OpenMode.ForRead);
                        foreach (ObjectId eid in btr)
                        {
                            var ent = tr.GetObject(eid, OpenMode.ForRead) as Entity;
                            if (ent == null || !ent.Layer.Equals(real, StringComparison.OrdinalIgnoreCase)) continue;
                            aBorrar.Add(eid);
                            string t = ent.GetType().Name;
                            porTipo[t] = porTipo.ContainsKey(t) ? porTipo[t] + 1 : 1;
                            total++;
                        }
                    }
                    if (confirmar)
                    {
                        foreach (var eid in aBorrar)
                        {
                            var w = tr.GetObject(eid, OpenMode.ForWrite);
                            w.Erase(true);
                        }
                        var candidatos = new ObjectIdCollection { id };
                        db.Purge(candidatos);
                        if (!candidatos.Contains(id))
                            throw new InvalidOperationException("La capa '" + real + "' sigue en uso después de borrar sus objetos " +
                                "(filtros, viewports u otra referencia). No se borró nada.");
                        tr.GetObject(id, OpenMode.ForWrite).Erase(true);
                        tr.Commit();
                    }
                    else tr.Abort();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD se negó (" + ex.ErrorStatus + "): " + ex.Message + ". No se borró nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            var tipos = new JsonObject();
            foreach (var kv in porTipo) tipos[kv.Key] = kv.Value;
            return new JsonObject
            {
                ["layer"] = real, ["deleted"] = confirmar, ["objects"] = total, ["byType"] = tipos,
                ["note"] = confirmar ? "Capa y objetos borrados." : "Nada borrado: pasá confirm=true para borrar la capa y sus " + total + " objeto(s)."
            };
        }

        // ============================================================ CAPAS CONGELADAS EN UN VIEWPORT (VPLAYER)

        /// <summary>params: handle (de un viewport de lámina, no el global), [freeze], [thaw], [thaw_all],
        /// [freeze_all_except]. Congela o descongela capas SOLO en ese viewport: con el modelo dibujado una vez,
        /// cada lámina muestra su disciplina sin tocar el modelo. Sin ninguna acción solo informa lo congelado.</summary>
        public static JsonObject ViewportLayers(Document doc, JsonObject pars)
        {
            string handle = Texto(pars, "handle");
            var congelar = Nombres(pars["freeze"]);
            var descongelar = Nombres(pars["thaw"]);
            var salvo = Nombres(pars["freeze_all_except"]);
            bool todas = pars["thaw_all"]?.GetValue<bool>() ?? false;
            if (salvo.Count > 0 && congelar.Count > 0)
                throw new ArgumentException("Usá 'freeze' o 'freeze_all_except', no los dos.");
            bool accion = congelar.Count > 0 || descongelar.Count > 0 || salvo.Count > 0 || todas;
            var db = doc.Database;
            var frozenNames = new JsonArray();
            int numero;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var vp = tr.GetObject(HandleHelper.GetObjectId(db, handle), accion ? OpenMode.ForWrite : OpenMode.ForRead) as Autodesk.AutoCAD.DatabaseServices.Viewport;
                    if (vp == null) throw new ArgumentException("'" + handle + "' no es un viewport.");
                    numero = vp.Number;
                    if (numero == 1)
                        throw new ArgumentException("Ese es el viewport global de la lámina (el que representa el papel): elegí un viewport que muestre el modelo.");
                    var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                    ObjectIdCollection Ids(List<string> ns)
                    {
                        var c = new ObjectIdCollection();
                        foreach (var n in ns)
                        {
                            if (!lt.Has(n)) throw new ArgumentException("No hay una capa llamada '" + n + "'.");
                            c.Add(lt[n]);
                        }
                        return c;
                    }
                    if (todas) vp.ThawAllLayersInViewport();
                    if (descongelar.Count > 0) vp.ThawLayersInViewport(Ids(descongelar).GetEnumerator());
                    if (congelar.Count > 0) vp.FreezeLayersInViewport(Ids(congelar).GetEnumerator());
                    if (salvo.Count > 0)
                    {
                        var mantener = new HashSet<ObjectId>(Ids(salvo).Cast<ObjectId>());
                        var resto = new ObjectIdCollection();
                        foreach (ObjectId id in lt)
                        {
                            var r = (LayerTableRecord)tr.GetObject(id, OpenMode.ForRead);
                            if (r.IsErased || mantener.Contains(id) || id == db.Clayer) continue;
                            resto.Add(id);
                        }
                        if (resto.Count > 0) vp.FreezeLayersInViewport(resto.GetEnumerator());
                    }
                    foreach (ObjectId id in vp.GetFrozenLayers())
                        frozenNames.Add(((LayerTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el cambio (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["viewport"] = handle, ["viewportNumber"] = numero, ["frozen"] = frozenNames, ["frozenCount"] = frozenNames.Count, ["changed"] = accion };
        }

        private static List<string> Nombres(JsonNode n)
        {
            var l = new List<string>();
            if (n == null) return l;
            if (!(n is JsonArray a)) throw new ArgumentException("Las listas de capas son arreglos de nombres.");
            foreach (var x in a) l.Add(x.GetValue<string>());
            return l;
        }

        // ============================================================ ESTADOS DE CAPA (LayerStateManager nativo)

        private static readonly string[] PropiedadesEstado = { "on", "frozen", "locked", "plot", "color", "linetype", "lineweight", "plotstyle", "transparency" };

        private static LayerStateMasks Mascara(JsonObject pars)
        {
            if (!(pars["properties"] is JsonArray pa) || pa.Count == 0)
                return LayerStateMasks.On | LayerStateMasks.Frozen | LayerStateMasks.Locked | LayerStateMasks.Plot | LayerStateMasks.Color |
                       LayerStateMasks.LineType | LayerStateMasks.LineWeight | LayerStateMasks.PlotStyle | LayerStateMasks.Transparency;
            var m = LayerStateMasks.None;
            foreach (var p in pa)
            {
                string s = (p.GetValue<string>() ?? "").ToLowerInvariant();
                switch (s)
                {
                    case "on": m |= LayerStateMasks.On; break;
                    case "frozen": m |= LayerStateMasks.Frozen; break;
                    case "locked": m |= LayerStateMasks.Locked; break;
                    case "plot": m |= LayerStateMasks.Plot; break;
                    case "color": m |= LayerStateMasks.Color; break;
                    case "linetype": m |= LayerStateMasks.LineType; break;
                    case "lineweight": m |= LayerStateMasks.LineWeight; break;
                    case "plotstyle": m |= LayerStateMasks.PlotStyle; break;
                    case "transparency": m |= LayerStateMasks.Transparency; break;
                    default:
                        throw new ArgumentException("Propiedad '" + s + "' desconocida. Válidas: " + string.Join(", ", PropiedadesEstado) + ".");
                }
            }
            return m;
        }

        private static string[] NombresDeMascara(LayerStateMasks m)
        {
            var l = new List<string>();
            if ((m & LayerStateMasks.On) != 0) l.Add("on");
            if ((m & LayerStateMasks.Frozen) != 0) l.Add("frozen");
            if ((m & LayerStateMasks.Locked) != 0) l.Add("locked");
            if ((m & LayerStateMasks.Plot) != 0) l.Add("plot");
            if ((m & LayerStateMasks.Color) != 0) l.Add("color");
            if ((m & LayerStateMasks.LineType) != 0) l.Add("linetype");
            if ((m & LayerStateMasks.LineWeight) != 0) l.Add("lineweight");
            if ((m & LayerStateMasks.PlotStyle) != 0) l.Add("plotstyle");
            if ((m & LayerStateMasks.Transparency) != 0) l.Add("transparency");
            return l.ToArray();
        }

        private static List<string> NombresEstados(LayerStateManager lsm, bool ocultos)
        {
            var l = new List<string>();
            foreach (var o in lsm.GetLayerStateNames(ocultos, false)) l.Add((string)o);
            return l;
        }

        /// <summary>params: name, [description], [properties] (on, frozen, locked, plot, color, linetype, lineweight,
        /// plotstyle, transparency; sin lista, todas), [replace]. Es el administrador de estados de capa de
        /// AutoCAD: el estado queda en el dibujo y se ve en el cuadro «Estados de capa».</summary>
        public static JsonObject StateSave(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            ValidarNombreEstado(nombre);
            if (nombre.StartsWith("_MCP_", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Los nombres que empiezan con _MCP_ son internos (aislar capas).");
            string desc = pars["description"]?.GetValue<string>() ?? "";
            if (desc.Length > 255) throw new ArgumentException("La descripción no puede pasar de 255 caracteres.");
            bool reemplazar = pars["replace"]?.GetValue<bool>() ?? false;
            var mascara = Mascara(pars);
            var lsm = doc.Database.LayerStateManager;
            bool existia = lsm.HasLayerState(nombre);
            if (existia && !reemplazar)
                throw new InvalidOperationException("Ya hay un estado llamado '" + nombre + "'. Pasá replace=true para reemplazarlo.");
            try
            {
                if (existia) lsm.DeleteLayerState(nombre);
                lsm.SaveLayerState(nombre, mascara, ObjectId.Null);
                if (desc.Length > 0) lsm.SetLayerStateDescription(nombre, desc);
            }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó guardar el estado (" + ex.ErrorStatus + "): " + ex.Message + ".");
            }
            return new JsonObject
            {
                ["name"] = nombre, ["replaced"] = existia, ["properties"] = new JsonArray(NombresDeMascara(mascara).Select(x => (JsonNode)x).ToArray()),
                ["layers"] = lsm.GetLayerStateLayers(nombre, false).Count
            };
        }

        /// <summary>params: name, [properties] (las mismas; sin lista, las que el estado guardó), [turn_off_others].
        /// Las capas del estado que ya no existen las trata AutoCAD según su política: acá se dejan como están.</summary>
        public static JsonObject StateRestore(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            var lsm = doc.Database.LayerStateManager;
            if (!lsm.HasLayerState(nombre))
                throw new ArgumentException("No hay un estado de capas llamado '" + nombre + "'. Mirá list_layer_states.");
            var mascara = pars["properties"] is JsonArray pa && pa.Count > 0 ? Mascara(pars) : lsm.GetLayerStateMask(nombre);
            bool apagar = pars["turn_off_others"]?.GetValue<bool>() ?? false;
            try
            {
                // 0 = no tocar las capas que el estado no menciona; 1 = apagarlas.
                lsm.RestoreLayerState(nombre, ObjectId.Null, apagar ? 1 : 0, mascara);
            }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó restaurar el estado (" + ex.ErrorStatus + "): " + ex.Message + ".");
            }
            return new JsonObject
            {
                ["name"] = nombre, ["restored"] = new JsonArray(NombresDeMascara(mascara).Select(x => (JsonNode)x).ToArray()),
                ["turnedOffOthers"] = apagar
            };
        }

        /// <summary>params: ninguno. Los estados del dibujo, con descripción, propiedades que guardan y cantidad de capas.</summary>
        public static JsonObject StateList(Document doc, JsonObject pars)
        {
            var lsm = doc.Database.LayerStateManager;
            var estados = new JsonArray();
            bool aislando = lsm.HasLayerState(EstadoAislar);
            foreach (var n in NombresEstados(lsm, true))
            {
                if (n.StartsWith("_MCP_", StringComparison.OrdinalIgnoreCase)) continue;
                var fila = new JsonObject { ["name"] = n };
                try
                {
                    fila["description"] = lsm.GetLayerStateDescription(n);
                    fila["properties"] = new JsonArray(NombresDeMascara(lsm.GetLayerStateMask(n)).Select(x => (JsonNode)x).ToArray());
                    fila["layers"] = lsm.GetLayerStateLayers(n, false).Count;
                    fila["hasViewportData"] = lsm.LayerStateHasViewportData(n);
                }
                catch (AcException ex) { fila["error"] = ex.Message; }
                estados.Add(fila);
            }
            return new JsonObject { ["states"] = estados, ["isolating"] = aislando, ["lastRestored"] = lsm.LastRestoredLayerState };
        }

        /// <summary>params: name.</summary>
        public static JsonObject StateDelete(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            if (nombre.StartsWith("_MCP_", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Ese estado es interno (aislar capas): usá unisolate_layers.");
            var lsm = doc.Database.LayerStateManager;
            if (!lsm.HasLayerState(nombre))
                throw new ArgumentException("No hay un estado de capas llamado '" + nombre + "'.");
            try { lsm.DeleteLayerState(nombre); }
            catch (AcException ex) { throw new InvalidOperationException("AutoCAD rechazó borrar el estado (" + ex.ErrorStatus + "): " + ex.Message + "."); }
            return new JsonObject { ["deleted"] = nombre };
        }

        // ============================================================ AISLAR CAPAS (LAYISO / LAYUNISO)

        /// <summary>params: layers[] (las que quedan visibles), [mode] off | lock. Guarda el estado previo en el
        /// administrador de estados de AutoCAD (como LAYISO con «_LAYISO_STATE») y apaga —o bloquea— todas las
        /// demás menos 0, Defpoints y la actual. Se deshace con unisolate_layers. No se anidan.</summary>
        public static JsonObject Isolate(Document doc, JsonObject pars)
        {
            var nombres = (pars["layers"] as JsonArray ?? throw new ArgumentException("Falta 'layers'."))
                .Select(n => n.GetValue<string>()).ToList();
            if (nombres.Count == 0) throw new ArgumentException("'layers' necesita al menos una capa.");
            string modo = (pars["mode"]?.GetValue<string>() ?? "off").ToLowerInvariant();
            if (modo != "off" && modo != "lock") throw new ArgumentException("'mode' es off o lock.");
            var db = doc.Database;
            var lsm = db.LayerStateManager;
            if (lsm.HasLayerState(EstadoAislar))
                throw new InvalidOperationException("Ya hay capas aisladas: usá unisolate_layers antes de aislar otras.");
            int afectadas = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                    var visibles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    foreach (var n in nombres)
                    {
                        if (!lt.Has(n)) throw new ArgumentException("No hay una capa llamada '" + n + "'.");
                        visibles.Add(((LayerTableRecord)tr.GetObject(lt[n], OpenMode.ForRead)).Name);
                    }
                    lsm.SaveLayerState(EstadoAislar, LayerStateMasks.On | LayerStateMasks.Locked, ObjectId.Null);
                    foreach (ObjectId id in lt)
                    {
                        var r = (LayerTableRecord)tr.GetObject(id, OpenMode.ForRead);
                        if (r.IsErased || visibles.Contains(r.Name) || EsProtegida(r.Name) || id == db.Clayer) continue;
                        var w = (LayerTableRecord)tr.GetObject(id, OpenMode.ForWrite);
                        if (modo == "off") { if (w.IsOff) continue; w.IsOff = true; }
                        else { if (w.IsLocked) continue; w.IsLocked = true; }
                        afectadas++;
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    try { if (lsm.HasLayerState(EstadoAislar)) lsm.DeleteLayerState(EstadoAislar); } catch (SysException) { }
                    throw new InvalidOperationException("AutoCAD rechazó aislar (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    try { if (lsm.HasLayerState(EstadoAislar)) lsm.DeleteLayerState(EstadoAislar); } catch (SysException) { }
                    throw;
                }
            }
            return new JsonObject { ["isolated"] = new JsonArray(nombres.Select(n => (JsonNode)n).ToArray()), ["mode"] = modo, ["layersAffected"] = afectadas };
        }

        /// <summary>params: ninguno. Devuelve las capas a como estaban antes de aislar (encendido y bloqueo).</summary>
        public static JsonObject Unisolate(Document doc, JsonObject pars)
        {
            var lsm = doc.Database.LayerStateManager;
            if (!lsm.HasLayerState(EstadoAislar))
                throw new InvalidOperationException("No hay capas aisladas (isolate_layers no se usó, o ya se deshizo).");
            try
            {
                lsm.RestoreLayerState(EstadoAislar, ObjectId.Null, 0, LayerStateMasks.On | LayerStateMasks.Locked);
                lsm.DeleteLayerState(EstadoAislar);
            }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó deshacer el aislamiento (" + ex.ErrorStatus + "): " + ex.Message + ".");
            }
            return new JsonObject { ["restored"] = true };
        }
    }
}
