using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Operaciones de edición que AutoCAD resuelve con su motor nativo:
    /// TRIM, EXTEND, FILLET, JOIN y OVERKILL.
    ///
    /// Por qué nativas y no reescritas. Recortar contra bordes, extender o
    /// empalmar con un radio son problemas de intersección con muchos casos
    /// (arcos, polilíneas con bulges, bordes implícitos) que AutoCAD ya
    /// resuelve; reimplementarlos a mano es una fuente de errores
    /// geométricos que un plano no perdona.
    ///
    /// Qué NO es esto. No es un ejecutor de comandos: cada operación tiene su
    /// comando FIJO, escrito acá, y recibe solo handles de entidades que
    /// existen y números; nadie de afuera elige qué comando corre ni le mete
    /// texto libre. Los tokens los arma este archivo.
    ///
    /// Cómo corre. Editor.Command solo anda dentro del contexto de un comando
    /// registrado, no desde el evento Idle donde corre el resto del plugin. La
    /// operación se valida y se deja anotada; se encola MCPNATIVEOP (comando
    /// registrado de este plugin) y recién ahí se ejecutan los tokens, agrupados
    /// en UN deshacer. El cliente pregunta el resultado con native_status.
    ///
    /// Las selecciones por punto (qué tramo recortar, qué esquina empalmar) se
    /// hacen sobre la entidad real: el punto se lleva al punto más cercano de la
    /// curva y la vista se encuadra un instante alrededor, porque el cursor de
    /// selección de AutoCAD mide en PÍXELES y a otra escala no acertaría. La
    /// vista se restaura al terminar.
    /// </summary>
    public static class NativeOpsCommand
    {
        private const int MaxLista = 500;

        private sealed class Job
        {
            public string Id;
            public string Op;
            public string DocName;
            public string State = "queued";           // queued | running | done | error
            public string Error;
            public string Warning;
            public double Ms;
            public Stopwatch Reloj = Stopwatch.StartNew();
            public long SeedBefore;
            public List<ObjectId> Involved = new List<ObjectId>();
            public Dictionary<ObjectId, double[]> BoxBefore = new Dictionary<ObjectId, double[]>();
            public HashSet<ObjectId> SpaceBefore;      // solo overkill sobre todo el espacio
            // Se construye DENTRO del contexto de comando (necesita la vista).
            public Func<Editor, object[]> Tokens;
            public Point3d? ViewCenter;
            public double ViewHeight;
            public Action<Editor> Before;
            public Action<Editor> After;
            public JsonArray Created = new JsonArray();
            public JsonArray Deleted = new JsonArray();
            public JsonArray Modified = new JsonArray();
            public int DeletedCount;
        }

        private static readonly object Lock = new object();
        private static Job _job;
        private static int _contador;

        // ------------------------------------------------------------ entrada

        /// <summary>params: op (trim|extend|fillet|join|overkill) y los de cada una.</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string op = pars["op"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(op))
                throw new ArgumentException("Falta 'op' (trim, extend, fillet, join u overkill).");
            op = op.ToLowerInvariant();

            GuardarEstado(doc);
            var db = doc.Database;

            var job = new Job { Op = op, DocName = doc.Name, SeedBefore = db.Handseed.Value };
            switch (op)
            {
                case "trim": PrepararTrimExtend(doc, pars, job, extend: false); break;
                case "extend": PrepararTrimExtend(doc, pars, job, extend: true); break;
                case "fillet": PrepararFillet(doc, pars, job); break;
                case "join": PrepararJoin(doc, pars, job); break;
                case "overkill": PrepararOverkill(doc, pars, job); break;
                default:
                    throw new ArgumentException("Operación '" + op + "' desconocida; válidas: trim, extend, fillet, join, overkill.");
            }
            SnapshotAntes(doc, job);

            lock (Lock)
            {
                if (_job != null && (_job.State == "queued" || _job.State == "running"))
                    throw new InvalidOperationException(
                        "Ya hay una operación en curso (" + _job.Id + "). Esperá su resultado con native_status.");
                job.Id = "op" + (++_contador);
                _job = job;
            }
            doc.SendStringToExecute("MCPNATIVEOP ", true, false, false);
            return new JsonObject
            {
                ["jobId"] = job.Id,
                ["state"] = "queued",
                ["note"] = "Se ejecuta apenas AutoCAD procese su cola; pedí el resultado con native_status."
            };
        }

        /// <summary>params: [jobId].</summary>
        public static JsonObject Status(Document doc, JsonObject pars)
        {
            string pedido = pars["jobId"]?.GetValue<string>();
            Job j;
            lock (Lock) j = _job;
            if (j == null || (pedido != null && pedido != j.Id))
                return new JsonObject { ["state"] = "desconocido",
                    ["note"] = "No hay una operación con ese id (solo se recuerda la última)." };
            var o = new JsonObject
            {
                ["jobId"] = j.Id, ["op"] = j.Op, ["state"] = j.State, ["document"] = j.DocName,
            };
            if (j.State == "done" || j.State == "error")
            {
                o["ms"] = j.Ms;
                o["created"] = j.Created.DeepClone();
                o["deleted"] = j.Deleted.DeepClone();
                o["deletedCount"] = j.DeletedCount;
                o["modified"] = j.Modified.DeepClone();
                o["changed"] = j.Created.Count + j.DeletedCount + j.Modified.Count > 0;
            }
            if (j.Error != null) o["error"] = j.Error;
            if (j.Warning != null) o["warning"] = j.Warning;
            return o;
        }

        // ------------------------------------------------------------ guardas

        private static object SysVarObj(string nombre)
        {
            try { return Application.GetSystemVariable(nombre); }
            catch (SysException) { return null; }
        }

        private static string SysVar(string nombre)
        {
            var o = SysVarObj(nombre);
            return o == null ? "" : Convert.ToString(o);
        }

        /// <summary>Se rechaza en milisegundos, con el motivo, en vez de
        /// mezclar la operación con lo que la persona está haciendo.</summary>
        private static void GuardarEstado(Document doc)
        {
            if (!doc.Editor.IsQuiescent)
                throw new InvalidOperationException(
                    "AutoCAD tiene un comando en curso (CMDNAMES='" + SysVar("CMDNAMES") +
                    "'). Esperá a que termine o cancelalo con ESC.");
            if (Convert.ToInt32(SysVarObj("BLOCKEDITOR") ?? 0) != 0)
                throw new InvalidOperationException("El editor de bloques está abierto: cerralo antes.");
            if (!string.IsNullOrEmpty(SysVar("REFEDITNAME")))
                throw new InvalidOperationException("Hay una referencia en edición en sitio (REFEDIT): cerrá la edición antes.");
            // Las selecciones por punto suponen una vista en planta del espacio activo.
            using (var v = doc.Editor.GetCurrentView())
            {
                if (!v.ViewDirection.IsParallelTo(Vector3d.ZAxis) || Math.Abs(v.ViewTwist) > 1e-9)
                    throw new InvalidOperationException(
                        "La vista no está en planta (hay 3D o rotación): hacé zoom_extents para volver a planta antes de editar.");
            }
        }

        // ------------------------------------------------------------ validación

        private static ObjectId Id(Document doc, JsonNode n, string cual)
        {
            string h = n?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h))
                throw new ArgumentException("Falta el handle de " + cual + ".");
            var id = HandleHelper.GetObjectId(doc.Database, h);
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                if (ent == null)
                    throw new ArgumentException("'" + h + "' no es una entidad de dibujo.");
                if (ent.BlockId != doc.Database.CurrentSpaceId)
                    throw new ArgumentException("'" + h + "' no está en el espacio activo (modelo o la lámina abierta).");
                tr.Commit();
            }
            return id;
        }

        private static List<ObjectId> Ids(Document doc, JsonNode n, string cual, int minimo)
        {
            var arr = n as JsonArray;
            if (arr == null || arr.Count < minimo)
                throw new ArgumentException("'" + cual + "' necesita al menos " + minimo + " handle(s).");
            var lista = new List<ObjectId>();
            foreach (var x in arr)
            {
                var id = Id(doc, x, cual);
                if (!lista.Contains(id)) lista.Add(id);
            }
            return lista;
        }

        private static Point3d Punto(JsonNode n, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count < 2 || a.Count > 3)
                throw new ArgumentException("'" + cual + "' tiene que ser [x, y] o [x, y, z].");
            double x = a[0].GetValue<double>(), y = a[1].GetValue<double>();
            double z = a.Count == 3 ? a[2].GetValue<double>() : 0.0;
            if (double.IsNaN(x) || double.IsNaN(y) || double.IsNaN(z)
                || double.IsInfinity(x) || double.IsInfinity(y) || double.IsInfinity(z))
                throw new ArgumentException("'" + cual + "' tiene coordenadas inválidas.");
            return new Point3d(x, y, z);
        }

        /// <summary>El punto elegido, llevado a la curva: así la selección
        /// acierta aunque el punto venga con un error de décimas.</summary>
        private static Point3d SobreCurva(Document doc, ObjectId id, Point3d p, out double diagonal)
        {
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var c = tr.GetObject(id, OpenMode.ForRead) as Curve;
                if (c == null)
                    throw new ArgumentException("Esta operación necesita una línea, arco, círculo o polilínea; la entidad es de otro tipo.");
                var e = c.GeometricExtents;
                diagonal = e.MinPoint.DistanceTo(e.MaxPoint);
                var q = c.GetClosestPointTo(p, false);
                tr.Commit();
                return q;
            }
        }

        // ------------------------------------------------------------ preparación

        private static void PrepararTrimExtend(Document doc, JsonObject pars, Job job, bool extend)
        {
            var bordes = Ids(doc, pars["edges"], extend ? "boundaries" : "edges", 1);
            var objetivo = Id(doc, pars["target"], "target");
            if (bordes.Contains(objetivo))
                throw new ArgumentException("El objetivo no puede ser también un borde.");
            var punto = Punto(pars["point"], "point");
            bool extendEdges = pars["extend_edges"]?.GetValue<bool>() ?? false;
            var p = SobreCurva(doc, objetivo, punto, out double diag);

            job.Involved.AddRange(bordes);
            job.Involved.Add(objetivo);
            job.ViewCenter = p;
            job.ViewHeight = Math.Max(diag * 0.4, 1e-3);
            string cmd = extend ? "_.EXTEND" : "_.TRIM";
            job.Tokens = ed =>
            {
                var t = new List<object> { cmd };
                foreach (var b in bordes) t.Add(b);
                t.Add("");                                   // fin de la selección de bordes
                if (extendEdges) { t.Add("_Edge"); t.Add("_Extend"); }
                t.Add(p);                                    // el tramo a recortar / el extremo a extender
                t.Add("");                                   // termina el comando
                return t.ToArray();
            };
        }

        private static void PrepararFillet(Document doc, JsonObject pars, Job job)
        {
            var a = Id(doc, pars["first"], "first");
            var b = Id(doc, pars["second"], "second");
            if (a == b) throw new ArgumentException("first y second son la misma entidad.");
            if (pars["radius"] == null) throw new ArgumentException("Falta 'radius' (0 = esquina viva).");
            double r = pars["radius"].GetValue<double>();
            if (double.IsNaN(r) || double.IsInfinity(r) || r < 0)
                throw new ArgumentException("'radius' tiene que ser un número >= 0.");
            var pa = SobreCurva(doc, a, Punto(pars["point1"], "point1"), out double da);
            var pb = SobreCurva(doc, b, Punto(pars["point2"], "point2"), out double db_);
            job.Involved.Add(a); job.Involved.Add(b);
            job.ViewCenter = new Point3d((pa.X + pb.X) / 2, (pa.Y + pb.Y) / 2, 0);
            job.ViewHeight = Math.Max(1.5 * (pa.DistanceTo(pb) + 2 * r), 1e-3);
            object radioAnterior = null;
            job.Before = ed =>
            {
                radioAnterior = SysVarObj("FILLETRAD");
                Application.SetSystemVariable("FILLETRAD", r);
            };
            job.After = ed =>
            {
                // Se restaura: FILLETRAD queda en el dibujo y la próxima persona no lo espera.
                if (radioAnterior != null)
                {
                    try { Application.SetSystemVariable("FILLETRAD", radioAnterior); } catch (SysException) { }
                }
            };
            job.Tokens = ed => new object[] { "_.FILLET", pa, pb };
        }

        private static void PrepararJoin(Document doc, JsonObject pars, Job job)
        {
            var ids = Ids(doc, pars["handles"], "handles", 2);
            job.Involved.AddRange(ids);
            job.Tokens = ed =>
            {
                var t = new List<object> { "_.JOIN" };
                foreach (var i in ids) t.Add(i);
                t.Add("");
                return t.ToArray();
            };
        }

        private static void PrepararOverkill(Document doc, JsonObject pars, Job job)
        {
            bool todo = pars["all"]?.GetValue<bool>() ?? false;
            List<ObjectId> ids;
            if (todo)
            {
                ids = new List<ObjectId>();
                job.SpaceBefore = new HashSet<ObjectId>();
                using (var tr = doc.Database.TransactionManager.StartTransaction())
                {
                    var btr = (BlockTableRecord)tr.GetObject(doc.Database.CurrentSpaceId, OpenMode.ForRead);
                    foreach (ObjectId id in btr)
                    {
                        if (id.IsErased) continue;
                        ids.Add(id);
                        job.SpaceBefore.Add(id);
                    }
                    tr.Commit();
                }
                if (ids.Count < 2)
                    throw new InvalidOperationException("Hay menos de 2 entidades en el espacio activo: no hay nada que depurar.");
            }
            else
            {
                ids = Ids(doc, pars["handles"], "handles", 2);
                job.Involved.AddRange(ids);
            }
            // -OVERKILL es la versión SIN diálogo (OVERKILL a secas abriría uno).
            job.Tokens = ed =>
            {
                var t = new List<object> { "_.-OVERKILL" };
                foreach (var i in ids) t.Add(i);
                t.Add("");        // fin de la selección
                t.Add("");        // acepta las opciones tal como están
                return t.ToArray();
            };
        }

        // ------------------------------------------------------------ medición antes / después

        private static double[] Caja(Transaction tr, ObjectId id)
        {
            try
            {
                var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                if (ent == null) return null;
                var e = ent.GeometricExtents;
                return new[] { e.MinPoint.X, e.MinPoint.Y, e.MaxPoint.X, e.MaxPoint.Y };
            }
            catch (SysException) { return null; }
        }

        private static void SnapshotAntes(Document doc, Job job)
        {
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                foreach (var id in job.Involved)
                    job.BoxBefore[id] = Caja(tr, id);
                tr.Commit();
            }
        }

        private static bool Igual(double[] a, double[] b)
        {
            if (a == null || b == null) return a == b;
            for (int i = 0; i < 4; i++)
                if (Math.Abs(a[i] - b[i]) > 1e-9) return false;
            return true;
        }

        private static void Medir(Document doc, Job job)
        {
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var revisar = new List<ObjectId>(job.Involved);
                if (job.SpaceBefore != null)
                    revisar = new List<ObjectId>(job.SpaceBefore);
                foreach (var id in revisar)
                {
                    bool borrada = id.IsErased;
                    if (borrada)
                    {
                        job.DeletedCount++;
                        if (job.Deleted.Count < MaxLista) job.Deleted.Add(id.Handle.ToString());
                        continue;
                    }
                    if (job.SpaceBefore != null) continue;       // en overkill total solo importan las borradas
                    var antes = job.BoxBefore.ContainsKey(id) ? job.BoxBefore[id] : null;
                    var despues = Caja(tr, id);
                    if (!Igual(antes, despues))
                    {
                        job.Modified.Add(new JsonObject
                        {
                            ["handle"] = id.Handle.ToString(),
                            ["before"] = antes == null ? null : new JsonArray(antes[0], antes[1], antes[2], antes[3]),
                            ["after"] = despues == null ? null : new JsonArray(despues[0], despues[1], despues[2], despues[3]),
                        });
                    }
                }
                var btr = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForRead);
                foreach (ObjectId id in btr)
                {
                    if (id.Handle.Value <= job.SeedBefore || id.IsErased) continue;
                    if (job.Created.Count >= MaxLista) break;
                    var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (ent == null) continue;
                    job.Created.Add(new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(),
                        ["type"] = ent.GetType().Name,
                        ["layer"] = ent.Layer,
                    });
                }
                tr.Commit();
            }
        }

        // ------------------------------------------------------------ ejecución

        /// <summary>Lo llama MCPNATIVEOP, ya dentro del contexto de comando.</summary>
        internal static void Ejecutar()
        {
            Job job;
            lock (Lock) job = _job;
            if (job == null || job.State != "queued")
                return;
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null) { Terminar(job, "No hay dibujo activo.", null); return; }
            if (doc.Name != job.DocName)
            {
                Terminar(job, "El dibujo activo cambió ('" + doc.Name + "' en vez de '" + job.DocName +
                              "'): no se tocó nada para no editar otro dibujo.", doc);
                return;
            }
            job.State = "running";
            var ed = doc.Editor;
            ViewTableRecord vista = null;
            object expert = null;
            try
            {
                expert = SysVarObj("EXPERT");
                try { Application.SetSystemVariable("EXPERT", (short)1); } catch (SysException) { }
                job.Before?.Invoke(ed);
                if (job.ViewCenter.HasValue)
                {
                    vista = ed.GetCurrentView();
                    using (var v = ed.GetCurrentView())
                    {
                        double aspecto = v.Width / v.Height;
                        v.CenterPoint = new Point2d(job.ViewCenter.Value.X, job.ViewCenter.Value.Y);
                        v.Height = job.ViewHeight;
                        v.Width = job.ViewHeight * aspecto;
                        ed.SetCurrentView(v);
                    }
                }
                var tokens = job.Tokens(ed);
                ed.Command(new object[] { "_.UNDO", "_Begin" });
                try { ed.Command(tokens); }
                finally
                {
                    try { ed.Command(new object[] { "_.UNDO", "_End" }); } catch (SysException) { }
                }
                Terminar(job, null, doc);
            }
            catch (AcException ex)
            {
                Terminar(job, "AutoCAD rechazó la operación: " + ex.ErrorStatus + " (" + ex.Message + ")", doc);
            }
            catch (SysException ex)
            {
                Terminar(job, ex.Message, doc);
            }
            finally
            {
                try { job.After?.Invoke(ed); } catch (SysException) { }
                if (vista != null)
                {
                    try { ed.SetCurrentView(vista); } catch (SysException) { }
                    vista.Dispose();
                }
                if (expert != null)
                {
                    try { Application.SetSystemVariable("EXPERT", expert); } catch (SysException) { }
                }
            }
        }

        private static void Terminar(Job job, string error, Document doc)
        {
            job.Error = error;
            if (doc != null)
            {
                string pendiente = SysVar("CMDNAMES");
                if (!string.IsNullOrEmpty(pendiente))
                {
                    job.Warning = "El comando quedó sin terminar (" + pendiente + "): se canceló con ESC.";
                    try { doc.SendStringToExecute("\u001b\u001b", true, false, false); } catch (SysException) { }
                }
                try { Medir(doc, job); }
                catch (SysException ex) { job.Warning = (job.Warning ?? "") + " No se pudo medir el resultado: " + ex.Message; }
                if (error == null && job.Created.Count + job.DeletedCount + job.Modified.Count == 0)
                    job.Warning = (job.Warning ?? "") + " La operación no cambió nada: puede que el punto no cayera sobre el " +
                                  "tramo correcto, que los bordes no corten al objetivo (usá extend_edges), o que la capa esté bloqueada.";
            }
            job.Ms = job.Reloj.ElapsedMilliseconds;
            job.State = error == null ? "done" : "error";
        }
    }

    /// <summary>Comando registrado dentro del cual corre Editor.Command.</summary>
    public class McpNativeOpCommands
    {
        [CommandMethod("MCPNATIVEOP")]
        public void RunOp()
        {
            NativeOpsCommand.Ejecutar();
        }
    }
}
