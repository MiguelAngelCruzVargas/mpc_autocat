using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AutoCadMcpPlugin.Commands.RunCode;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// run_code: compila y corre C# contra la API de AutoCAD.
    ///
    /// Es la puerta para todo lo que no tiene comando propio (3D, vistas,
    /// lo que sea): sin ella, cada capacidad nueva costaba un comando C#, una
    /// recompilación y un reinicio de AutoCAD. El orden de las barreras
    /// importa y es este: contraseña → compilar → filtro → ejecutar.
    /// Nada se ejecuta si alguna falla, y todo queda en run_code.log.
    ///
    /// Este archivo NO referencia tipos de Roslyn (ver CompileOutcome): si
    /// Roslyn no carga dentro de AutoCAD, la excepción sale de Compilar() y se
    /// atrapa acá, en vez de romper el JIT de este método.
    /// </summary>
    public static class RunCodeCommand
    {
        private const int MaxCreados = 500;

        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var reloj = Stopwatch.StartNew();
            string code = pars["code"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(code))
                throw new ArgumentException("Falta 'code': el cuerpo C# a ejecutar.");
            string password = pars["password"]?.GetValue<string>() ?? "";
            string description = pars["description"]?.GetValue<string>() ?? "";
            bool compileOnly = pars["compile_only"]?.GetValue<bool>() ?? false;

            RunCodeConfig cfg;
            try
            {
                cfg = RunCodeAccess.Verify(password);
            }
            catch (InvalidOperationException ex)
            {
                RunCodeAccess.Log("rechazo", description, reloj.ElapsedMilliseconds, code, ex.Message);
                throw;
            }

            CompileOutcome comp;
            try
            {
                comp = Compilar(code, cfg.PermitirSistema);
            }
            catch (Exception ex) when (ex is FileNotFoundException || ex is FileLoadException
                                       || ex is TypeLoadException || ex is MissingMethodException
                                       || ex is BadImageFormatException)
            {
                // Sin Roslyn no hay filtro semántico, así que no hay plan B
                // que ejecute igual: se dice por qué y no se corre nada.
                var msg = "No se pudo cargar el compilador (Roslyn) dentro de AutoCAD: " +
                          ex.GetType().Name + ": " + ex.Message +
                          ". Sin él no hay filtro de seguridad, así que no se ejecutó nada.";
                RunCodeAccess.Log("error", description, reloj.ElapsedMilliseconds, code, msg);
                throw new InvalidOperationException(msg);
            }

            var r = new JsonObject
            {
                ["compiled"] = comp.Errors.Count == 0,
                ["engine"] = "roslyn",
                ["cached"] = comp.FromCache,
                ["result"] = null,
                ["output"] = "",
                ["created"] = new JsonArray(),
                ["errors"] = ErroresJson(comp.Errors),
                ["blocked"] = BloqueosJson(comp.Blocked),
                ["exception"] = null,
                ["aborted"] = false,
            };

            if (comp.Errors.Count > 0)
                return Cerrar(r, reloj, "error de compilación", description, code);
            if (comp.Blocked.Count > 0)
                return Cerrar(r, reloj, "bloqueo", description, code,
                              comp.Blocked.Count + " uso(s) fuera de lo permitido");
            if (compileOnly)
                return Cerrar(r, reloj, "compile_only", description, code);

            Ejecutar(doc, comp.ScriptType, r);
            bool fallo = r["aborted"]?.GetValue<bool>() ?? false;
            return Cerrar(r, reloj, fallo ? "excepción" : "ok", description, code,
                          fallo ? r["exception"]?["message"]?.GetValue<string>() : null);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private static CompileOutcome Compilar(string code, bool permitirSistema)
            => RunCodeCompiler.Compile(code, permitirSistema);

        /// <summary>
        /// Una sola transacción: si el código tira una excepción, se descarta
        /// entera y el dibujo queda exactamente como estaba. Lo creado se
        /// detecta con ObjectAppended, no confiando en lo que el código diga.
        /// </summary>
        private static void Ejecutar(Document doc, Type tipo, JsonObject r)
        {
            var db = doc.Database;
            var nuevos = new List<ObjectId>();
            ObjectEventHandler alAgregar = (s, e) =>
            {
                try { nuevos.Add(e.DBObject.ObjectId); } catch (Exception) { }
            };

            ScriptBase script = null;
            Exception falla = null;
            db.ObjectAppended += alAgregar;
            try
            {
                using (var tr = db.TransactionManager.StartTransaction())
                {
                    try
                    {
                        script = (ScriptBase)Activator.CreateInstance(tipo);
                        script.Init(doc, tr);
                        object valor = script.Run();
                        // Se serializa ANTES del commit: si devuelve entidades
                        // abiertas en esta transacción, después ya están cerradas.
                        r["result"] = Serializar(valor, 0);
                        tr.Commit();
                    }
                    catch (Exception ex)
                    {
                        falla = ex;
                    }
                }
            }
            finally
            {
                db.ObjectAppended -= alAgregar;
            }

            r["output"] = script?.Output ?? "";
            if (falla != null)
            {
                r["aborted"] = true;
                r["result"] = null;
                var ex = falla is System.Reflection.TargetInvocationException tie && tie.InnerException != null
                    ? tie.InnerException : falla;
                var info = new JsonObject
                {
                    ["type"] = ex.GetType().FullName,
                    ["message"] = ex.Message,
                };
                int? linea = LineaDelCodigo(ex);
                if (linea.HasValue)
                    info["line"] = linea.Value;
                r["exception"] = info;
                return;
            }

            r["created"] = Creados(db, nuevos, out int total);
            if (total > MaxCreados)
                r["createdTotal"] = total;
        }

        private static JsonArray Creados(Database db, List<ObjectId> ids, out int total)
        {
            var arr = new JsonArray();
            total = 0;
            var vistos = new HashSet<ObjectId>();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (var id in ids)
                {
                    if (id.IsNull || id.IsErased || !vistos.Add(id))
                        continue;
                    if (!(tr.GetObject(id, OpenMode.ForRead, false) is Entity ent))
                        continue;
                    total++;
                    if (arr.Count >= MaxCreados)
                        continue;
                    JsonNode bbox = null;
                    try
                    {
                        var ext = ent.GeometricExtents;
                        bbox = new JsonArray(ext.MinPoint.X, ext.MinPoint.Y, ext.MinPoint.Z,
                                             ext.MaxPoint.X, ext.MaxPoint.Y, ext.MaxPoint.Z);
                    }
                    catch (Exception) { }
                    arr.Add(new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(),
                        ["type"] = ent.GetType().Name,
                        ["layer"] = ent.Layer,
                        ["bbox"] = bbox,
                    });
                }
                tr.Commit();
            }
            return arr;
        }

        /// <summary>"codigo.cs:línea 7" (o ":line 7") en el stack, gracias al PDB.</summary>
        private static int? LineaDelCodigo(Exception ex)
        {
            var m = Regex.Match(ex.StackTrace ?? "", @"codigo\.cs:\D*(\d+)");
            return m.Success && int.TryParse(m.Groups[1].Value, out int n) ? n : (int?)null;
        }

        private static JsonObject Cerrar(JsonObject r, Stopwatch reloj, string resultado,
                                         string description, string code, string detalle = null)
        {
            r["elapsedMs"] = reloj.ElapsedMilliseconds;
            RunCodeAccess.Log(resultado, description, reloj.ElapsedMilliseconds, code, detalle);
            return r;
        }

        private static JsonArray ErroresJson(List<CompileError> errores)
        {
            var arr = new JsonArray();
            foreach (var e in errores)
                arr.Add(new JsonObject
                {
                    ["line"] = e.Line, ["column"] = e.Column, ["message"] = e.Message,
                    ["severity"] = e.Severity, ["id"] = e.Id,
                });
            return arr;
        }

        private static JsonArray BloqueosJson(List<Blocked> bloqueos)
        {
            var arr = new JsonArray();
            foreach (var b in bloqueos)
                arr.Add(new JsonObject
                {
                    ["line"] = b.Line, ["column"] = b.Column, ["symbol"] = b.Symbol, ["reason"] = b.Reason,
                });
            return arr;
        }

        /// <summary>
        /// Lo que devuelve el código, a JSON. Los tipos de AutoCAD van a la
        /// forma que ya usan las demás tools (handle, [x,y,z]); lo que no se
        /// conoce sale como ToString() en vez de romper la respuesta.
        /// </summary>
        private static JsonNode Serializar(object v, int profundidad)
        {
            if (v == null)
                return null;
            if (profundidad > 6)
                return JsonValue.Create(v.ToString());
            switch (v)
            {
                case string s: return JsonValue.Create(s);
                case bool b: return JsonValue.Create(b);
                case double d: return double.IsNaN(d) || double.IsInfinity(d) ? null : JsonValue.Create(d);
                case float f: return float.IsNaN(f) || float.IsInfinity(f) ? null : JsonValue.Create((double)f);
                case int i: return JsonValue.Create(i);
                case long l: return JsonValue.Create(l);
                case short sh: return JsonValue.Create((int)sh);
                case byte by: return JsonValue.Create((int)by);
                case uint ui: return JsonValue.Create((long)ui);
                case decimal m: return JsonValue.Create(m);
                case ObjectId id: return id.IsNull ? null : JsonValue.Create(id.Handle.ToString());
                case Handle h: return JsonValue.Create(h.ToString());
                case Point3d p: return new JsonArray(p.X, p.Y, p.Z);
                case Vector3d vec: return new JsonArray(vec.X, vec.Y, vec.Z);
                case Point2d p2: return new JsonArray(p2.X, p2.Y);
                case Vector2d v2: return new JsonArray(v2.X, v2.Y);
                case Extents3d e:
                    return new JsonObject
                    {
                        ["min"] = new JsonArray(e.MinPoint.X, e.MinPoint.Y, e.MinPoint.Z),
                        ["max"] = new JsonArray(e.MaxPoint.X, e.MaxPoint.Y, e.MaxPoint.Z),
                    };
                case Entity ent:
                    return new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(), ["type"] = ent.GetType().Name,
                        ["layer"] = ent.Layer,
                    };
                case DBObject o:
                    return new JsonObject { ["handle"] = o.Handle.ToString(), ["type"] = o.GetType().Name };
                case Enum en: return JsonValue.Create(en.ToString());
                case IDictionary dic:
                {
                    var obj = new JsonObject();
                    foreach (DictionaryEntry kv in dic)
                        obj[kv.Key?.ToString() ?? "null"] = Serializar(kv.Value, profundidad + 1);
                    return obj;
                }
                case IEnumerable lista:
                {
                    var arr = new JsonArray();
                    foreach (var x in lista)
                    {
                        if (arr.Count >= 1000)
                        {
                            arr.Add("[... recortado a 1000 elementos]");
                            break;
                        }
                        arr.Add(Serializar(x, profundidad + 1));
                    }
                    return arr;
                }
                default:
                    return JsonValue.Create(v.ToString());
            }
        }
    }
}
