using System;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading;

namespace AutoCadMcpPlugin.Commands.RunCode
{
    /// <summary>Lo que dice run_code.json, ya validado.</summary>
    internal sealed class RunCodeConfig
    {
        public bool PermitirSistema;
    }

    /// <summary>
    /// Quién puede usar run_code, y el registro de todo lo que se corrió.
    ///
    /// run_code ejecuta código dentro de acad.exe con los permisos del usuario.
    /// Por eso nace APAGADO y solo lo prende el usuario, a mano, con una
    /// contraseña que elige él (tools/run_code_acceso.py activar). La IA no
    /// tiene forma de prenderlo: el archivo de configuración no se puede
    /// escribir desde run_code (System.IO está fuera de lo permitido).
    ///
    /// El archivo se relee en CADA llamada: desactivar tiene efecto inmediato,
    /// sin reiniciar AutoCAD.
    /// </summary>
    internal static class RunCodeAccess
    {
        private static readonly object LogLock = new object();
        private const long MaxLog = 5L * 1024 * 1024;

        private static string Dir => Path.GetDirectoryName(PluginEntry.PortFilePath);
        private static string ConfigPath => Path.Combine(Dir, "run_code.json");
        private static string LogPath => Path.Combine(Dir, "run_code.log");

        public static RunCodeConfig Verify(string password)
        {
            const string Apagado =
                "run_code está apagado. Lo activa el usuario con: " +
                "python tools/run_code_acceso.py activar";

            JsonObject cfg;
            try
            {
                if (!File.Exists(ConfigPath))
                    throw new InvalidOperationException(Apagado);
                cfg = JsonNode.Parse(File.ReadAllText(ConfigPath, Encoding.UTF8)) as JsonObject;
            }
            catch (InvalidOperationException) { throw; }
            catch (Exception ex)
            {
                throw new InvalidOperationException(
                    "run_code está apagado: no se pudo leer run_code.json (" + ex.Message +
                    "). El usuario lo reactiva con: python tools/run_code_acceso.py activar");
            }

            if (cfg == null || !LeerBool(cfg, "habilitado"))
                throw new InvalidOperationException(Apagado);

            byte[] sal = DeHex(cfg["sal"]?.GetValue<string>());
            byte[] esperado = DeHex(cfg["hash"]?.GetValue<string>());
            if (sal == null || esperado == null || esperado.Length != 32)
                throw new InvalidOperationException(
                    "run_code está apagado: run_code.json no tiene sal/hash válidos. " +
                    "El usuario lo reactiva con: python tools/run_code_acceso.py activar");

            byte[] clave = Encoding.UTF8.GetBytes(password ?? "");
            byte[] mezcla = new byte[sal.Length + clave.Length];
            Buffer.BlockCopy(sal, 0, mezcla, 0, sal.Length);
            Buffer.BlockCopy(clave, 0, mezcla, sal.Length, clave.Length);
            byte[] calculado;
            using (var sha = SHA256.Create())
                calculado = sha.ComputeHash(mezcla);

            if (!IgualesEnTiempoConstante(calculado, esperado))
            {
                // Frena el probar contraseñas en serie. Es el hilo de AutoCAD,
                // pero un segundo por intento fallido es un costo aceptable.
                Thread.Sleep(1000);
                throw new InvalidOperationException("run_code: contraseña incorrecta.");
            }

            return new RunCodeConfig { PermitirSistema = LeerBool(cfg, "permitir_sistema") };
        }

        /// <summary>
        /// Una entrada por llamada: aceptada, rechazada, bloqueada o con error.
        /// Nunca la contraseña. Si el log no se puede escribir, no se frena el
        /// trabajo: el registro es para revisar, no una condición para correr.
        /// </summary>
        public static void Log(string resultado, string description, long elapsedMs,
                               string code, string detalle = null)
        {
            try
            {
                lock (LogLock)
                {
                    Directory.CreateDirectory(Dir);
                    var info = new FileInfo(LogPath);
                    if (info.Exists && info.Length > MaxLog)
                    {
                        var viejo = LogPath + ".1";
                        if (File.Exists(viejo))
                            File.Delete(viejo);
                        File.Move(LogPath, viejo);
                    }
                    var sb = new StringBuilder();
                    sb.Append("===== ")
                      .Append(DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture))
                      .Append(" | ").Append(resultado)
                      .Append(" | ").Append(elapsedMs).Append(" ms")
                      .Append(" | ").Append(string.IsNullOrWhiteSpace(description) ? "(sin descripción)" : description)
                      .AppendLine();
                    if (!string.IsNullOrEmpty(detalle))
                        sb.Append("-- ").AppendLine(detalle);
                    sb.AppendLine(code ?? "");
                    File.AppendAllText(LogPath, sb.ToString(), Encoding.UTF8);
                }
            }
            catch (Exception)
            {
            }
        }

        private static bool LeerBool(JsonObject o, string clave)
        {
            try { return o[clave]?.GetValue<bool>() ?? false; }
            catch (Exception) { return false; }
        }

        private static byte[] DeHex(string hex)
        {
            if (string.IsNullOrEmpty(hex) || hex.Length % 2 != 0)
                return null;
            var r = new byte[hex.Length / 2];
            for (int i = 0; i < r.Length; i++)
            {
                if (!byte.TryParse(hex.Substring(2 * i, 2), NumberStyles.HexNumber,
                                   CultureInfo.InvariantCulture, out r[i]))
                    return null;
            }
            return r;
        }

        private static bool IgualesEnTiempoConstante(byte[] a, byte[] b)
        {
            if (a.Length != b.Length)
                return false;
            int diferencia = 0;
            for (int i = 0; i < a.Length; i++)
                diferencia |= a[i] ^ b[i];
            return diferencia == 0;
        }
    }
}
