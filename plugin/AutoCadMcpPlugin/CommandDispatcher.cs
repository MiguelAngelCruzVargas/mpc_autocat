using System;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Parsea el request JSON, lo ejecuta en el hilo de documento de AutoCAD
    /// (obligatorio para tocar la base de datos) y arma la respuesta JSON.
    /// </summary>
    public static class CommandDispatcher
    {
        public static string Dispatch(string requestJson)
        {
            string id = null;
            try
            {
                var req = JsonNode.Parse(requestJson).AsObject();
                id = req["id"]?.GetValue<string>();
                var cmd = req["cmd"]?.GetValue<string>();
                var pars = req["params"] as JsonObject ?? new JsonObject();

                if (string.IsNullOrEmpty(cmd))
                    throw new ArgumentException("Falta 'cmd' en el request.");

                JsonObject result = RunOnDocumentThread(cmd, pars);
                return BuildResponse(id, true, result, null);
            }
            catch (Exception ex)
            {
                return BuildResponse(id, false, null, Unwrap(ex).Message);
            }
        }

        /// <summary>
        /// Task.Wait()/GetResult() envuelven la excepción real en un
        /// AggregateException cuyo Message es un genérico "uno o varios
        /// errores" — desenvolvemos hasta la causa real para que el cliente
        /// (Python/Claude) vea el mensaje útil.
        /// </summary>
        private static Exception Unwrap(Exception ex)
        {
            while (ex is AggregateException agg && agg.InnerException != null)
                ex = agg.InnerException;
            return ex;
        }

        /// <summary>
        /// Cuanto esperamos a que AutoCAD ejecute el comando. TIENE que ser
        /// MENOR que el timeout del cliente Python (ACAD_MCP_TIMEOUT): si el
        /// cliente se rinde primero, cierra el socket y del lado de aca se
        /// escribe sobre un stream muerto.
        /// </summary>
        private static readonly int TimeoutSeconds = ReadTimeoutSeconds();

        private static int ReadTimeoutSeconds()
        {
            var raw = Environment.GetEnvironmentVariable("ACAD_MCP_EXEC_TIMEOUT");
            return int.TryParse(raw, out var parsed) && parsed > 0 ? parsed : 60;
        }

        private static JsonObject RunOnDocumentThread(string cmd, JsonObject pars)
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null)
                throw new InvalidOperationException("No hay ningún dibujo abierto en AutoCAD.");

            var tcs = new TaskCompletionSource<JsonObject>();

            // MainThreadQueue encola el trabajo para que corra en el hilo
            // principal de AutoCAD (el único que puede tocar la Database de
            // forma segura), disparado desde Application.Idle. Bloqueamos el
            // hilo del socket hasta que termine, con timeout por si AutoCAD
            // nunca llega a estar idle (p.ej. un diálogo modal abierto).
            MainThreadQueue.Post(() =>
            {
                try
                {
                    using (doc.LockDocument())
                    {
                        JsonObject r = Handlers.Execute(cmd, doc, pars);
                        tcs.SetResult(r);
                    }
                }
                catch (Exception ex)
                {
                    tcs.SetException(ex);
                }
            });

            if (!tcs.Task.Wait(TimeSpan.FromSeconds(TimeoutSeconds)))
                throw new TimeoutException(
                    "AutoCAD no procesó el comando a tiempo. ¿Hay algún diálogo modal abierto en AutoCAD?");

            return tcs.Task.GetAwaiter().GetResult();
        }

        private static string BuildResponse(string id, bool ok, JsonObject result, string error)
        {
            var resp = new JsonObject
            {
                ["id"] = id,
                ["ok"] = ok
            };
            if (ok)
                resp["result"] = result;
            else
                resp["error"] = error;

            return resp.ToJsonString();
        }
    }
}
