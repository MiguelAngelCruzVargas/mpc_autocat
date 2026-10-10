using System;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

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

        /// <summary>
        /// Comandos que NO pueden correr con el documento bloqueado, porque
        /// cambian cual es el documento activo. AutoCAD tira eLockViolation
        /// si se abre o se crea un dibujo teniendo tomado el lock de otro.
        /// </summary>
        private static bool RunsUnlocked(string cmd)
        {
            return cmd == "open_document" || cmd == "new_document"
                || cmd == "close_document";
        }

        /// <summary>
        /// Comandos que tienen sentido SIN ningún dibujo abierto.
        ///
        /// AutoCAD puede quedar corriendo con cero documentos (se cierra el
        /// último y la ventana sigue ahí). Hasta acá TODO comando fallaba en
        /// ese estado -- incluido new_document, cuyo trabajo es justamente
        /// crear uno. Se descubrió con AutoCAD abierto y vacío: no había
        /// forma de salir de ahí desde el MCP.
        /// </summary>
        private static bool WorksWithoutDocument(string cmd)
        {
            return cmd == "new_document" || cmd == "open_document"
                || cmd == "list_documents" || cmd == "ping";
        }

        private static JsonObject RunOnDocumentThread(string cmd, JsonObject pars)
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            if (doc == null && !WorksWithoutDocument(cmd))
                throw new InvalidOperationException(
                    "No hay ningún dibujo abierto en AutoCAD. Abrí uno, o usá " +
                    "new_document / open_document, que funcionan igual sin ninguno.");

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
                    if (doc == null || RunsUnlocked(cmd))
                    {
                        // Abrir o crear un dibujo con el lock de OTRO tomado
                        // tira eLockViolation. Estos comandos no tocan la
                        // Database del documento actual, asi que no lo
                        // necesitan.
                        tcs.SetResult(Handlers.Execute(cmd, doc, pars));
                        return;
                    }
                    // El activo se relee ACÁ, en el hilo principal: entre que
                    // el socket recibió el comando y que AutoCAD quedó idle
                    // pudo cambiar (new_document, set_active_document).
                    var actual = Application.DocumentManager.MdiActiveDocument ?? doc;
                    using (actual.LockDocument())
                    {
                        // WorkingDatabase NO sigue al documento activo cuando
                        // se cambia por API: queda apuntando al anterior un
                        // rato. Toda entidad nueva (DBText, Polyline) toma de
                        // ahí sus defaults -- estilo de texto, capa, tipo de
                        // línea -- y al agregarla al dibujo activo AutoCAD
                        // tira eWrongDatabase o eKeyNotFound. Pasó en vivo con
                        // test_live_instalaciones: el cuadro de cargas y los
                        // contactos fallaban después de un new_document.
                        // No se restaura: el anterior es justamente el valor viejo.
                        if (!ReferenceEquals(HostApplicationServices.WorkingDatabase, actual.Database))
                            HostApplicationServices.WorkingDatabase = actual.Database;
                        JsonObject r = Handlers.Execute(cmd, actual, pars);
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
