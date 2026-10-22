using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// RESTRICCIONES PARAMÉTRICAS 2D (la cinta «Paramétrico»: GC* geométricas y DC* dimensionales) con la API de asociatividad
    /// de AutoCAD (Assoc2dConstraintGroup, AssocNetwork, AssocVariable). Se descubrió probando en vivo con run_code, porque
    /// el descompilado solo muestra las firmas:
    ///   - la red se pide con AssocNetwork.GetInstanceFromObject(espacio, true, true, "ACAD_ASSOCNETWORK");
    ///   - el grupo se crea con new Assoc2dConstraintGroup(plano), se agrega con Database.AddDBObject y AddAction;
    ///   - la geometría entra con AddConstrainedGeometry(FullSubentityPath(entidad, Edge 1)) —con Null o Edge 0 da
    ///     eInvalidInput—; los puntos (inicio, fin, centro) salen de ConstrainedCurve.ConstrainedImplicitPoints;
    ///   - la variable de una cota se fija con SetExpression(expr, "", ...) (un evaluador con nombre da eKeyNotFound);
    ///   - la distancia SIN cota (dimDependencyId nulo) funciona, la restricción de valor SÍ pide el AssocValueDependency;
    ///   - el solver decide qué entidad se mueve (no siempre la primera): para que algo no se mueva, se le pone «fix».
    ///   - RADIO/DIÁMETRO: AddRadiusDiameterConstraint da eInconsistentConstraint en un círculo suelto (ver tool: pendiente).
    /// Cada operación va en UNA transacción: una restricción contradictoria (eInconsistentConstraint) no deja nada a medias.
    /// </summary>
    public static class ConstraintCommands
    {
        private const string ClaveRed = "ACAD_ASSOCNETWORK";

        private static readonly Dictionary<string, GeometricalConstraint.ConstraintType> Geometricas =
            new Dictionary<string, GeometricalConstraint.ConstraintType>(StringComparer.OrdinalIgnoreCase)
            {
                { "horizontal", GeometricalConstraint.ConstraintType.Horizontal },
                { "vertical", GeometricalConstraint.ConstraintType.Vertical },
                { "parallel", GeometricalConstraint.ConstraintType.Parallel },
                { "perpendicular", GeometricalConstraint.ConstraintType.Perpendicular },
                { "collinear", GeometricalConstraint.ConstraintType.Collinear },
                { "coincident", GeometricalConstraint.ConstraintType.Coincident },
                { "concentric", GeometricalConstraint.ConstraintType.Concentric },
                { "tangent", GeometricalConstraint.ConstraintType.Tangent },
                { "equal_length", GeometricalConstraint.ConstraintType.EqualLength },
                { "equal_radius", GeometricalConstraint.ConstraintType.EqualRadius },
                { "fix", GeometricalConstraint.ConstraintType.Fix },
            };

        // ------------------------------------------------------------ utilidades

        private static Entity Entidad(Transaction tr, Database db, string handle, OpenMode modo = OpenMode.ForRead)
        {
            var id = HandleHelper.GetObjectId(db, handle);
            var e = tr.GetObject(id, modo) as Entity;
            if (e == null) throw new ArgumentException("'" + handle + "' no es una entidad de dibujo.");
            if (e.BlockId != db.CurrentSpaceId) throw new ArgumentException("'" + handle + "' no está en el espacio activo.");
            if (!(e is Line) && !(e is Circle) && !(e is Arc) && !(e is Ellipse) && !(e is Polyline))
                throw new ArgumentException("'" + handle + "' es un " + e.GetType().Name + ": las restricciones valen para línea, círculo, arco, elipse y polilínea.");
            return e;
        }

        private static AssocNetwork Red(Transaction tr, Database db)
        {
            var id = AssocNetwork.GetInstanceFromObject(db.CurrentSpaceId, true, true, ClaveRed);
            return (AssocNetwork)tr.GetObject(id, OpenMode.ForWrite);
        }

        private static Assoc2dConstraintGroup Grupo(Transaction tr, Database db, AssocNetwork red)
        {
            foreach (ObjectId aid in red.GetActions)
            {
                var g = tr.GetObject(aid, OpenMode.ForWrite) as Assoc2dConstraintGroup;
                if (g != null && g.WorkPlane.Normal.IsParallelTo(Vector3d.ZAxis)) return g;
            }
            var nuevo = new Assoc2dConstraintGroup(new Plane(Point3d.Origin, Vector3d.ZAxis));
            ObjectId gid = db.AddDBObject(nuevo);
            tr.AddNewlyCreatedDBObject(nuevo, true);
            red.AddAction(gid, true);
            return nuevo;
        }

        private static FullSubentityPath Ruta(Entity e, JsonObject objetivo)
        {
            int indice = 1;                                        // línea, círculo, arco, elipse: «Edge 1»
            if (e is Polyline pl)
            {
                int seg = objetivo["segment"]?.GetValue<int>() ?? throw new ArgumentException("Una polilínea necesita 'segment' (el tramo, desde 0).");
                if (seg < 0 || seg >= (pl.Closed ? pl.NumberOfVertices : pl.NumberOfVertices - 1))
                    throw new ArgumentException("La polilínea no tiene el tramo " + seg + ".");
                indice = seg + 1;
            }
            return new FullSubentityPath(new[] { e.ObjectId }, new SubentityId(SubentityType.Edge, (IntPtr)indice));
        }

        private static ConstrainedGeometry Geometria(Transaction tr, Database db, Assoc2dConstraintGroup g, JsonObject objetivo)
        {
            string h = objetivo["handle"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h)) throw new ArgumentException("Cada objetivo necesita 'handle'.");
            var e = Entidad(tr, db, h);
            var ruta = Ruta(e, objetivo);
            string punto = objetivo["point"]?.GetValue<string>();
            ConstrainedGeometry cg = null;
            try { cg = g.GetConstrainedGeometry(ruta, punto == "mid"); } catch (AcException) { cg = null; }
            if (cg == null) cg = g.AddConstrainedGeometry(ruta);
            if (string.IsNullOrEmpty(punto)) return cg;
            var curva = cg as ConstrainedCurve;
            if (curva == null) throw new ArgumentException("'" + h + "' no tiene puntos restringibles.");
            ImplicitPointType tipo;
            switch (punto.ToLowerInvariant())
            {
                case "start": tipo = ImplicitPointType.StartImplicit; break;
                case "end": tipo = ImplicitPointType.EndImplicit; break;
                case "mid": tipo = ImplicitPointType.MidImplicit; break;
                case "center": tipo = ImplicitPointType.CenterImplicit; break;
                default: throw new ArgumentException("'point' es start, end, mid o center.");
            }
            foreach (var p in curva.ConstrainedImplicitPoints)
                if (p.PointType == tipo) return p;
            throw new ArgumentException("'" + h + "' (" + e.GetType().Name + ") no tiene el punto '" + punto + "'.");
        }

        private static JsonObject Caja(Entity e)
        {
            try
            {
                var x = e.GeometricExtents;
                return new JsonObject { ["handle"] = e.Handle.ToString(), ["type"] = e.GetType().Name,
                    ["bbox"] = new JsonArray(x.MinPoint.X, x.MinPoint.Y, x.MaxPoint.X, x.MaxPoint.Y) };
            }
            catch (SysException) { return new JsonObject { ["handle"] = e.Handle.ToString() }; }
        }

        private static JsonArray Cajas(Transaction tr, Database db, IEnumerable<string> handles)
        {
            var a = new JsonArray();
            foreach (var h in handles.Distinct())
                a.Add(Caja((Entity)tr.GetObject(HandleHelper.GetObjectId(db, h), OpenMode.ForRead)));
            return a;
        }

        private static IEnumerable<string> Handles(JsonArray objetivos)
        {
            foreach (var o in objetivos) yield return ((JsonObject)o)["handle"].GetValue<string>();
        }

        private static InvalidOperationException Traducir(AcException ex, string que)
        {
            string es = ex.ErrorStatus.ToString();
            string pista = es == "InconsistentConstraint" ? " Contradice las restricciones que ya tiene (o no se puede satisfacer)." :
                           es == "InvalidInput" ? " AutoCAD no admite esa combinación de entidades o puntos." : "";
            return new InvalidOperationException("AutoCAD rechazó " + que + " (" + es + ")." + pista + " No se cambió nada.");
        }

        private static string Estado(Assoc2dConstraintGroup g)
        {
            try { return g.SolutionStatus(true).ToString(); } catch (SysException) { return "desconocido"; }
        }

        // ------------------------------------------------------------ restricción geométrica

        /// <summary>params: type (horizontal | vertical | parallel | perpendicular | collinear | coincident | concentric | tangent |
        /// equal_length | equal_radius | fix), targets [{handle, [point: start|end|mid|center], [segment]}...]. Resuelve la geometría y
        /// devuelve las cajas antes y después, los grados de libertad y el estado.</summary>
        public static JsonObject AddGeometric(Document doc, JsonObject pars)
        {
            string tipoTxt = pars["type"]?.GetValue<string>() ?? "";
            if (!Geometricas.TryGetValue(tipoTxt, out var tipo))
                throw new ArgumentException("type '" + tipoTxt + "' no existe. Hay: " + string.Join(", ", Geometricas.Keys) + ".");
            var objetivos = pars["targets"] as JsonArray;
            if (objetivos == null || objetivos.Count == 0) throw new ArgumentException("Falta 'targets'.");
            int minimo = (tipo == GeometricalConstraint.ConstraintType.Horizontal || tipo == GeometricalConstraint.ConstraintType.Vertical ||
                          tipo == GeometricalConstraint.ConstraintType.Fix) ? 1 : 2;
            if (objetivos.Count < minimo) throw new ArgumentException(tipoTxt + " necesita al menos " + minimo + " objetivo(s).");
            if (objetivos.Count > 8) throw new ArgumentException("Máximo 8 objetivos.");
            var db = doc.Database;
            JsonArray antes, despues; int dof; string estado;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    antes = Cajas(tr, db, Handles(objetivos));
                    var red = Red(tr, db);
                    var g = Grupo(tr, db, red);
                    var geoms = objetivos.Select(o => Geometria(tr, db, g, (JsonObject)o)).ToArray();
                    g.AddGeometricalConstraint(tipo, geoms);
                    AssocManager.EvaluateTopLevelNetwork(db, null, 0);
                    despues = Cajas(tr, db, Handles(objetivos));
                    dof = g.GetDOF; estado = Estado(g);
                    tr.Commit();
                }
                catch (AcException ex) { tr.Abort(); throw Traducir(ex, "la restricción " + tipoTxt); }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["type"] = tipoTxt, ["before"] = antes, ["after"] = despues, ["degreesOfFreedom"] = dof, ["status"] = estado };
        }

        // ------------------------------------------------------------ restricción dimensional

        /// <summary>params: kind (distance | horizontal | vertical | angle), targets (distance: 2 puntos [{handle, point}] o UNA línea
        /// [{handle}] —su largo—; horizontal/vertical: igual; angle: 2 líneas), value (número; en grados para angle), [name] (nombre de
        /// la variable; por defecto d1, d2...), [dimension=true] (dibuja la cota), [offset] (separación de la cota).</summary>
        public static JsonObject AddDimensional(Document doc, JsonObject pars)
        {
            string kind = (pars["kind"]?.GetValue<string>() ?? "").ToLowerInvariant();
            if (kind != "distance" && kind != "horizontal" && kind != "vertical" && kind != "angle")
                throw new ArgumentException("kind es distance, horizontal, vertical o angle (radio y diámetro: pendiente).");
            var objetivos = pars["targets"] as JsonArray;
            if (objetivos == null || objetivos.Count < 1 || objetivos.Count > 2) throw new ArgumentException("'targets' lleva 1 o 2 objetivos.");
            double valor = pars["value"]?.GetValue<double>() ?? throw new ArgumentException("Falta 'value'.");
            if (double.IsNaN(valor) || double.IsInfinity(valor) || valor <= 0) throw new ArgumentException("'value' tiene que ser un número mayor que cero.");
            if (kind == "angle" && valor >= 360) throw new ArgumentException("El ángulo va de 0 a 360 grados.");
            bool conCota = pars["dimension"]?.GetValue<bool>() ?? true;
            string nombre = pars["name"]?.GetValue<string>();
            if (nombre != null && (nombre.Length == 0 || nombre.Length > 60 || !char.IsLetter(nombre[0]) || nombre.Any(c => !char.IsLetterOrDigit(c) && c != '_')))
                throw new ArgumentException("'name' empieza con letra y lleva letras, números o guion bajo (hasta 60).");
            var db = doc.Database;
            JsonArray antes, despues; int dof; string estado; string nombreFinal; string dimHandle = null;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    antes = Cajas(tr, db, Handles(objetivos));
                    var red = Red(tr, db);
                    var g = Grupo(tr, db, red);
                    var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
                    nombreFinal = nombre ?? SiguienteNombre(tr, red, kind == "angle" ? "ang" : "d");
                    foreach (ObjectId aid in red.GetActions)
                        if (tr.GetObject(aid, OpenMode.ForRead) is AssocVariable existente && existente.Name.Equals(nombreFinal, StringComparison.OrdinalIgnoreCase))
                            throw new ArgumentException("Ya hay una variable llamada '" + nombreFinal + "': elegí otro nombre o usá set_constraint_value.");

                    // variable + dependencia de valor
                    var v = new AssocVariable();
                    ObjectId vid = db.AddDBObject(v); tr.AddNewlyCreatedDBObject(v, true); red.AddAction(vid, true);
                    v.SetName(nombreFinal, true);
                    string err = "";
                    v.SetExpression(valor.ToString("R", CultureInfo.InvariantCulture), "", true, true, ref err, true);
                    var vd = new AssocValueDependency();
                    ObjectId vdId = db.AddDBObject(vd); tr.AddNewlyCreatedDBObject(vd, true);
                    vd.AttachToObject(new CompoundObjectId(vid));

                    ObjectId dimDep = ObjectId.Null;
                    Func<Dimension, ObjectId> poner = d =>
                    {
                        espacio.AppendEntity(d); tr.AddNewlyCreatedDBObject(d, true);
                        dimHandle = d.Handle.ToString();
                        ObjectId dep = ObjectId.Null, body = ObjectId.Null;
                        AssocDimDependencyBody.CreateAndPostToDatabase(d.ObjectId, ref dep, ref body);
                        return dep;
                    };

                    if (kind == "angle")
                    {
                        if (objetivos.Count != 2) throw new ArgumentException("angle necesita 2 líneas.");
                        var e1 = (Line)(Entidad(tr, db, objetivos[0]["handle"].GetValue<string>()) as Line ?? throw new ArgumentException("El ángulo se mide entre dos LÍNEAS."));
                        var e2 = (Line)(Entidad(tr, db, objetivos[1]["handle"].GetValue<string>()) as Line ?? throw new ArgumentException("El ángulo se mide entre dos LÍNEAS."));
                        var g1 = Geometria(tr, db, g, new JsonObject { ["handle"] = e1.Handle.ToString() }) as ConstrainedLine ?? throw new InvalidOperationException("La primera línea no es restringible como recta.");
                        var g2 = Geometria(tr, db, g, new JsonObject { ["handle"] = e2.Handle.ToString() }) as ConstrainedLine ?? throw new InvalidOperationException("La segunda línea no es restringible como recta.");
                        if (conCota)
                        {
                            var m1 = e1.StartPoint + (e1.EndPoint - e1.StartPoint) * 0.5; var m2 = e2.StartPoint + (e2.EndPoint - e2.StartPoint) * 0.5;
                            var arco = new Point3d((m1.X + m2.X) / 2, (m1.Y + m2.Y) / 2, 0);
                            dimDep = poner(new LineAngularDimension2(e1.StartPoint, e1.EndPoint, e2.StartPoint, e2.EndPoint, arco, "", db.Dimstyle));
                        }
                        g.AddAngularConstraint(g1, g2, AngularConstraint.AngularSectorType.ParallelAntiClockwise, vdId, dimDep);
                    }
                    else
                    {
                        ConstrainedGeometry p1, p2; Point3d q1, q2;
                        if (objetivos.Count == 2)
                        {
                            p1 = Geometria(tr, db, g, (JsonObject)objetivos[0]); p2 = Geometria(tr, db, g, (JsonObject)objetivos[1]);
                            if (!(p1 is ConstrainedPoint) || !(p2 is ConstrainedPoint)) throw new ArgumentException("Con dos objetivos, cada uno lleva 'point' (start, end, mid o center).");
                            q1 = ((ConstrainedPoint)p1).Point; q2 = ((ConstrainedPoint)p2).Point;
                        }
                        else
                        {
                            var l = Entidad(tr, db, objetivos[0]["handle"].GetValue<string>()) as Line ?? throw new ArgumentException("Con un solo objetivo tiene que ser una LÍNEA (se restringe su largo).");
                            var gl = (ConstrainedCurve)Geometria(tr, db, g, (JsonObject)objetivos[0]);
                            p1 = gl.ConstrainedImplicitPoints.First(p => p.PointType == ImplicitPointType.StartImplicit);
                            p2 = gl.ConstrainedImplicitPoints.First(p => p.PointType == ImplicitPointType.EndImplicit);
                            q1 = l.StartPoint; q2 = l.EndPoint;
                        }
                        var tipoDir = kind == "distance" ? DistanceConstraint.DistanceDirectionType.NotDirected : DistanceConstraint.DistanceDirectionType.FixedDirection;
                        var dir = kind == "vertical" ? Vector3d.YAxis : Vector3d.XAxis;
                        if (conCota)
                        {
                            double sep = pars["offset"]?.GetValue<double>() ?? Math.Max(q1.DistanceTo(q2) * 0.25, 1e-3);
                            var mid = new Point3d((q1.X + q2.X) / 2, (q1.Y + q2.Y) / 2, 0);
                            if (kind == "distance")
                            {
                                var d = q2 - q1; var n = new Vector3d(-d.Y, d.X, 0); if (n.Length > 1e-12) n = n.GetNormal() * sep;
                                dimDep = poner(new AlignedDimension(q1, q2, mid + n, "", db.Dimstyle));
                            }
                            else if (kind == "horizontal")
                                dimDep = poner(new RotatedDimension(0, q1, q2, new Point3d(mid.X, Math.Min(q1.Y, q2.Y) - sep, 0), "", db.Dimstyle));
                            else
                                dimDep = poner(new RotatedDimension(Math.PI / 2, q1, q2, new Point3d(Math.Max(q1.X, q2.X) + sep, mid.Y, 0), "", db.Dimstyle));
                        }
                        g.AddDistanceConstraint(p1, p2, tipoDir, vdId, dimDep, dir, null);
                    }
                    AssocManager.EvaluateTopLevelNetwork(db, null, 0);
                    despues = Cajas(tr, db, Handles(objetivos));
                    dof = g.GetDOF; estado = Estado(g);
                    tr.Commit();
                }
                catch (AcException ex) { tr.Abort(); throw Traducir(ex, "la restricción de " + kind); }
                catch (SysException) { tr.Abort(); throw; }
            }
            var r = new JsonObject { ["kind"] = kind, ["name"] = nombreFinal, ["value"] = valor, ["before"] = antes, ["after"] = despues,
                                     ["degreesOfFreedom"] = dof, ["status"] = estado };
            if (dimHandle != null) r["dimension"] = dimHandle;
            return r;
        }

        private static string SiguienteNombre(Transaction tr, AssocNetwork red, string prefijo)
        {
            var usados = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (ObjectId aid in red.GetActions)
                if (tr.GetObject(aid, OpenMode.ForRead) is AssocVariable v) usados.Add(v.Name);
            for (int i = 1; ; i++) if (!usados.Contains(prefijo + i)) return prefijo + i;
        }

        // ------------------------------------------------------------ valor, lista y borrado

        /// <summary>params: name (de la variable), value. Cambia el parámetro y el dibujo sigue: es lo que hace paramétrico al plano.</summary>
        public static JsonObject SetValue(Document doc, JsonObject pars)
        {
            string nombre = pars["name"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(nombre)) throw new ArgumentException("Falta 'name'.");
            double valor = pars["value"]?.GetValue<double>() ?? throw new ArgumentException("Falta 'value'.");
            if (double.IsNaN(valor) || double.IsInfinity(valor) || valor <= 0) throw new ArgumentException("'value' tiene que ser un número mayor que cero.");
            var db = doc.Database;
            string anterior; double[] caja = null; int dof; string estado;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var red = Red(tr, db);
                    AssocVariable v = null;
                    foreach (ObjectId aid in red.GetActions)
                        if (tr.GetObject(aid, OpenMode.ForWrite) is AssocVariable x && x.Name.Equals(nombre, StringComparison.OrdinalIgnoreCase)) { v = x; break; }
                    if (v == null) throw new ArgumentException("No hay una variable llamada '" + nombre + "'. Mirá list_constraints.");
                    anterior = v.Expression;
                    string err = "";
                    v.SetExpression(valor.ToString("R", CultureInfo.InvariantCulture), "", true, true, ref err, true);
                    AssocManager.EvaluateTopLevelNetwork(db, null, 0);
                    var g = Grupo(tr, db, red);
                    dof = g.GetDOF; estado = Estado(g);
                    tr.Commit();
                }
                catch (AcException ex) { tr.Abort(); throw Traducir(ex, "el nuevo valor de '" + nombre + "' (" + valor + ")"); }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["name"] = nombre, ["previous"] = anterior, ["value"] = valor, ["degreesOfFreedom"] = dof, ["status"] = estado };
        }

        /// <summary>params: ninguno. Variables (nombre, expresión) y restricciones del espacio activo, con grados de libertad y estado.</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var vars = new JsonArray(); var grupos = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                if (!AssocManager.HasAssocNetwork(db))
                {
                    tr.Commit();
                    return new JsonObject { ["variables"] = vars, ["groups"] = grupos, ["note"] = "Este dibujo no tiene restricciones." };
                }
                var redId = AssocNetwork.GetInstanceFromObject(db.CurrentSpaceId, false, true, ClaveRed);
                if (redId.IsNull) { tr.Commit(); return new JsonObject { ["variables"] = vars, ["groups"] = grupos, ["note"] = "El espacio activo no tiene restricciones." }; }
                var red = (AssocNetwork)tr.GetObject(redId, OpenMode.ForRead);
                foreach (ObjectId aid in red.GetActions)
                {
                    var o = tr.GetObject(aid, OpenMode.ForRead);
                    if (o is AssocVariable v) vars.Add(new JsonObject { ["name"] = v.Name, ["expression"] = v.Expression });
                    else if (o is Assoc2dConstraintGroup g)
                    {
                        var cs = new JsonArray();
                        foreach (var c in g.Constraints) cs.Add(new JsonObject { ["type"] = c.GetType().Name.Replace("Constraint", ""), ["internal"] = c.IsInternal, ["active"] = c.IsActive });
                        var ents = new JsonArray();
                        foreach (var cg in g.ConstrainedGeometries)
                            foreach (var p in cg.FullSubentityPaths) foreach (var i in p.GetObjectIds()) ents.Add(i.Handle.ToString());
                        grupos.Add(new JsonObject { ["degreesOfFreedom"] = g.GetDOF, ["status"] = Estado(g), ["constraints"] = cs, ["entities"] = ents });
                    }
                }
                tr.Commit();
            }
            return new JsonObject { ["variables"] = vars, ["groups"] = grupos };
        }

        /// <summary>params: [handles] (quita esas entidades del grupo y sus restricciones) o all=true (borra todas las restricciones y variables
        /// del espacio activo). Las entidades no se borran ni se mueven.</summary>
        public static JsonObject Remove(Document doc, JsonObject pars)
        {
            bool todo = pars["all"]?.GetValue<bool>() ?? false;
            var hs = pars["handles"] as JsonArray;
            if (todo == (hs != null && hs.Count > 0)) throw new ArgumentException("Pasá 'handles' o all=true, uno de los dos.");
            var db = doc.Database;
            int quitadas = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var redId = AssocNetwork.GetInstanceFromObject(db.CurrentSpaceId, false, true, ClaveRed);
                    if (redId.IsNull)
                    {
                        if (todo) { tr.Commit(); return new JsonObject { ["removed"] = 0, ["note"] = "El espacio activo no tenía restricciones." }; }
                        throw new InvalidOperationException("El espacio activo no tiene restricciones.");
                    }
                    var red = (AssocNetwork)tr.GetObject(redId, OpenMode.ForWrite);
                    if (todo)
                    {
                        var ids = new List<ObjectId>();
                        foreach (ObjectId aid in red.GetActions) ids.Add(aid);
                        foreach (var aid in ids) { red.RemoveAction(aid, true); quitadas++; }
                    }
                    else
                    {
                        var objetivos = new HashSet<ObjectId>(hs.Select(h => HandleHelper.GetObjectId(db, h.GetValue<string>())));
                        foreach (ObjectId aid in red.GetActions)
                        {
                            var g = tr.GetObject(aid, OpenMode.ForWrite) as Assoc2dConstraintGroup;
                            if (g == null) continue;
                            foreach (var cg in g.ConstrainedGeometries.ToArray())
                            {
                                bool es = false;
                                foreach (var p in cg.FullSubentityPaths) foreach (var i in p.GetObjectIds()) if (objetivos.Contains(i)) es = true;
                                if (es) { g.DeleteConstrainedGeometry(cg.GeomDependencyId); quitadas++; }
                            }
                        }
                    }
                    tr.Commit();
                }
                catch (AcException ex) { tr.Abort(); throw Traducir(ex, "quitar las restricciones"); }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["removed"] = quitadas };
        }
    }
}
