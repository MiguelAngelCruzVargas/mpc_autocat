using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Win32;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Verifica la licencia de AutoCAD IA DENTRO del plugin: es la capa que hace cumplir (la de Python solo avisa con mejores mensajes).
    ///
    /// El archivo %LOCALAPPDATA%\AutoCadMcp\licencia.json trae un token firmado por el servidor de licencias con ECDSA P-256 (formato
    /// base64url(cuerpo JSON) + "." + base64url(r||s)). Aca solo se VERIFICA, con la clave publica: no se puede fabricar una licencia
    /// sin la privada, que nunca sale del servidor. Se comprueba la firma, que el token sea de ESTE equipo (hash del MachineGuid, igual
    /// que licencia.py), que no haya vencido y que el reloj no se haya atrasado respecto de lo ya visto.
    ///
    /// Solo se exige con la constante de compilacion LICENCIA (dotnet build -p:Licencia=true, lo que hace empaquetar.ps1). Un build de
    /// desarrollo informa el estado pero no bloquea nada. Ping y license_status nunca se bloquean.
    /// </summary>
    public static class LicenciaGuard
    {
        // Mismo punto P-256 sin comprimir (65 bytes) que mcp_server/licencia.py: se genera con licencias/generar_claves.py.
        private const string ClavePublicaB64 = "BKfr7hVUaeNp+zRv0GuwOi89ZOHrIBrT+FdcEIz0BHPkWjXVyQZ/sJs4oUM7hEBLUDbsl1ZgBsbrAeEslx19vvc=";

#if LICENCIA
        public const bool Obligatoria = true;
#else
        public const bool Obligatoria = false;
#endif

        private static readonly string Archivo = Path.Combine(
            Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "AutoCadMcp", "licencia.json");

        private static readonly object Candado = new object();
        private static DateTime _leidoEn = DateTime.MinValue;
        private static DateTime _mtime = DateTime.MinValue;
        private static JsonObject _estado;

        /// <summary>Lanza InvalidOperationException (con el mensaje que ve el usuario) si no hay licencia valida.</summary>
        public static void Exigir(string cmd)
        {
            if (!Obligatoria || cmd == "ping" || cmd == "license_status") return;
            var e = Estado();
            if (!e["valida"].GetValue<bool>())
                throw new InvalidOperationException("LICENCIA: " + e["mensaje"].GetValue<string>());
        }

        public static JsonObject Estado()
        {
            lock (Candado)
            {
                DateTime mt;
                try { mt = File.Exists(Archivo) ? File.GetLastWriteTimeUtc(Archivo) : DateTime.MinValue; }
                catch (IOException) { mt = DateTime.MinValue; }
                if (_estado != null && mt == _mtime && (DateTime.UtcNow - _leidoEn).TotalSeconds < 20) return _estado;
                _estado = Calcular(DateTimeOffset.UtcNow.ToUnixTimeSeconds());
                _mtime = mt;
                _leidoEn = DateTime.UtcNow;
                return _estado;
            }
        }

        private static JsonObject Mal(string motivo, string mensaje, string plan = null)
        {
            return new JsonObject { ["valida"] = false, ["motivo"] = motivo, ["mensaje"] = mensaje, ["plan"] = plan, ["obligatoria"] = Obligatoria };
        }

        private static JsonObject Calcular(long ahora)
        {
            string token; double visto = 0;
            try
            {
                if (!File.Exists(Archivo))
                    return Mal("sin_licencia", "AutoCAD IA no tiene licencia en este equipo. Activa una clave (activate_license) o empieza la prueba gratis de 7 dias (start_trial).");
                var d = JsonNode.Parse(File.ReadAllText(Archivo)) as JsonObject;
                token = d?["token"]?.GetValue<string>();
                if (d?["visto"] != null) visto = d["visto"].GetValue<double>();
            }
            catch (Exception)
            {
                return Mal("token_invalido", "El archivo de licencia esta danado. Vuelve a activar la licencia.");
            }
            if (string.IsNullOrEmpty(token))
                return Mal("sin_licencia", "AutoCAD IA no tiene licencia en este equipo. Activa una clave (activate_license) o empieza la prueba gratis de 7 dias (start_trial).");

            JsonObject p;
            try { p = Verificar(token); }
            catch (Exception) { return Mal("token_invalido", "El archivo de licencia no es valido (firma incorrecta). Vuelve a activar la licencia."); }

            string plan = p["plan"]?.GetValue<string>();
            if (p["maquina"]?.GetValue<string>() != IdEquipo())
                return Mal("otro_equipo", "Esta licencia esta activada para otro equipo. Activala aqui con tu clave.", plan);
            if (ahora < visto - 2 * 3600)
                return Mal("reloj", "El reloj del equipo esta atrasado respecto a la ultima vez que se uso. Corrige la fecha y hora de Windows.", plan);
            double hasta = p["valido_hasta"]?.GetValue<double>() ?? 0;
            double? lic = p["licencia_hasta"] == null ? (double?)null : p["licencia_hasta"].GetValue<double>();
            if (ahora > hasta)
            {
                if (lic.HasValue && ahora > lic.Value)
                    return Mal("vencida", "La licencia vencio. Renuevala para seguir usando AutoCAD IA.", plan);
                return Mal("token_vencido", "No se pudo renovar la licencia (hace mas de 7 dias sin conexion con el servidor). Conectate a internet un momento.", plan);
            }
            var ok = new JsonObject
            {
                ["valida"] = true, ["motivo"] = "ok", ["plan"] = plan, ["obligatoria"] = Obligatoria,
                ["mensaje"] = "Licencia " + plan + " activa.", ["valido_hasta"] = hasta
            };
            if (lic.HasValue) ok["licencia_hasta"] = lic.Value;
            return ok;
        }

        private static byte[] B64u(string s)
        {
            s = s.Replace('-', '+').Replace('_', '/');
            return Convert.FromBase64String(s.PadRight(s.Length + (4 - s.Length % 4) % 4, '='));
        }

        private static JsonObject Verificar(string token)
        {
            var partes = token.Split('.');
            if (partes.Length != 2) throw new FormatException("token");
            var cuerpo = B64u(partes[0]);
            var firma = B64u(partes[1]);
            if (firma.Length != 64) throw new FormatException("firma");
            var q = Convert.FromBase64String(ClavePublicaB64);
            if (q.Length != 65 || q[0] != 4) throw new FormatException("clave publica");
            var x = new byte[32]; var y = new byte[32];
            Array.Copy(q, 1, x, 0, 32); Array.Copy(q, 33, y, 0, 32);
            var prm = new ECParameters { Curve = ECCurve.NamedCurves.nistP256, Q = new ECPoint { X = x, Y = y } };
            using (var ecdsa = ECDsa.Create(prm))
            {
                if (!ecdsa.VerifyData(cuerpo, firma, HashAlgorithmName.SHA256))
                    throw new CryptographicException("firma");
            }
            return JsonNode.Parse(Encoding.UTF8.GetString(cuerpo)) as JsonObject;
        }

        /// <summary>sha256("autocad-ia|" + MachineGuid), igual que id_equipo() de licencia.py.</summary>
        public static string IdEquipo()
        {
            string guid = "";
            try
            {
                using (var b = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
                using (var k = b.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography"))
                    guid = Convert.ToString(k?.GetValue("MachineGuid"));
            }
            catch (Exception) { }
            using (var sha = SHA256.Create())
            {
                var h = sha.ComputeHash(Encoding.UTF8.GetBytes("autocad-ia|" + guid));
                var sb = new StringBuilder();
                foreach (var b in h) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }
    }
}
