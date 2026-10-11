using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Varios comandos en UN viaje.
    ///
    /// Cada comando cuesta ~0.5 s aunque no haga nada (la cola se vacía en
    /// Application.Idle). Un detalle constructivo son 200-400 entidades: dos a
    /// tres minutos por prueba, cuando dibujarlas toma un segundo. Con esto un
    /// detalle se dibuja en un solo viaje y se puede iterar mirándolo en
    /// AutoCAD, que es la única prueba que vale.
    ///
    /// params: commands = [{"id": "$b1_0", "cmd": "create_polyline",
    ///                      "params": {...}, "fallback": {...}?}, ...]
    ///
    /// Un string de los params igual al 'id' de un comando anterior se
    /// reemplaza por el handle que devolvió (así un achurado toma el contorno
    /// creado en el mismo lote). Si un comando falla y trae 'fallback', se
    /// reintenta con esos params (un patrón de achurado que no existe en esta
    /// instalación cae al de respaldo). Un error no corta el lote: se informa
    /// en su posición.
    /// </summary>
    public static class BatchCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var cmds = pars["commands"]?.AsArray()
                ?? throw new ArgumentException("batch: falta 'commands'.");
            var handles = new Dictionary<string, string>();
            var results = new JsonArray();
            int errores = 0;
            foreach (var node in cmds)
            {
                var item = node.AsObject();
                string id = item["id"]?.GetValue<string>();
                string cmd = item["cmd"].GetValue<string>();
                if (cmd == "batch")
                    throw new ArgumentException("batch no se anida.");
                var p = Resolve(item["params"]?.DeepClone() ?? new JsonObject(), handles).AsObject();
                JsonObject r = null;
                string error = null;
                try
                {
                    r = Handlers.Execute(cmd, doc, p);
                }
                catch (Exception ex)
                {
                    error = ex.Message;
                    if (item["fallback"] is JsonObject fb)
                    {
                        var p2 = Resolve(fb.DeepClone(), handles).AsObject();
                        try
                        {
                            r = Handlers.Execute(cmd, doc, p2);
                            r["usedFallback"] = true;
                            r["primaryError"] = error;
                            error = null;
                        }
                        catch (Exception ex2)
                        {
                            error = error + " | fallback: " + ex2.Message;
                        }
                    }
                }
                var res = new JsonObject { ["id"] = id, ["ok"] = error == null };
                if (r != null)
                {
                    res["result"] = r;
                    if (id != null && r["handle"] != null)
                        handles[id] = r["handle"].GetValue<string>();
                }
                else
                {
                    res["error"] = error;
                    errores++;
                }
                results.Add(res);
            }
            return new JsonObject { ["results"] = results, ["errors"] = errores };
        }

        private static JsonNode Resolve(JsonNode node, Dictionary<string, string> handles)
        {
            switch (node)
            {
                case JsonObject o:
                    var keys = new List<string>();
                    foreach (var kv in o) keys.Add(kv.Key);
                    foreach (var k in keys)
                        if (o[k] != null) o[k] = Resolve(o[k].DeepClone(), handles);
                    return o;
                case JsonArray a:
                    var nuevo = new JsonArray();
                    foreach (var x in a)
                        nuevo.Add(x == null ? null : Resolve(x.DeepClone(), handles));
                    return nuevo;
                case JsonValue v:
                    if (v.TryGetValue<string>(out var s) && s.StartsWith("$")
                        && handles.TryGetValue(s, out var h))
                        return JsonValue.Create(h);
                    return v;
                default:
                    return node;
            }
        }
    }
}
