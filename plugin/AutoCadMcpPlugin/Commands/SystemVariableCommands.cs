using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Variables de sistema de AutoCAD (hay cientos: LTSCALE, OSMODE, DIMSCALE,
    /// PICKFIRST, LUNITS, CMDECHO...). Leerlas y cambiarlas es la mitad de lo
    /// que hace una persona frente a AutoCAD, y hasta ahora el plugin solo
    /// tocaba unas pocas, escondidas dentro de otras tools.
    ///
    /// get_system_variables: lee varias de una sola llamada.
    /// set_system_variable: cambia UNA y devuelve el valor anterior, para poder
    /// restaurarla. Las que gobiernan seguridad o qué se carga solo no se
    /// pueden cambiar desde acá.
    /// get_editor_state: en qué está AutoCAD (comando en curso, editor de
    /// bloques, documento y espacio activos): lo que hay que mirar antes de
    /// mandarle trabajo.
    /// </summary>
    public static class SystemVariableCommands
    {
        private const int MaxLecturas = 100;

        /// <summary>Seguridad y carga automática: las cambia una persona.</summary>
        internal static readonly HashSet<string> Protegidas = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase)
        {
            "SECURELOAD", "TRUSTEDPATHS", "TRUSTEDDOMAINS", "LEGACYCODESEARCH",
            "DEMANDLOAD", "SAVEFILEPATH", "SAVEFILE", "ACADLSPASDOC",
            "LISPSYS", "SECURITYFLAGS", "STARTUP", "FILEDIA", "CMDDIA",
            "PROXY", "WEBMESSAGES"
        };

        /// <summary>params: names = ["LTSCALE", "OSMODE", ...]</summary>
        public static JsonObject Get(Document doc, JsonObject pars)
        {
            var nombres = pars["names"] as JsonArray;
            if (nombres == null || nombres.Count == 0)
                throw new ArgumentException("Falta 'names': la lista de variables de sistema a leer.");
            if (nombres.Count > MaxLecturas)
                throw new ArgumentException("Pediste " + nombres.Count + " variables; el máximo es " + MaxLecturas + ".");
            var valores = new JsonObject();
            var errores = new JsonObject();
            foreach (var n in nombres)
            {
                string nombre = n?.GetValue<string>();
                if (string.IsNullOrWhiteSpace(nombre))
                    continue;
                try
                {
                    valores[nombre.ToUpperInvariant()] = ToJson(Application.GetSystemVariable(nombre));
                }
                catch (AcException ex)
                {
                    errores[nombre.ToUpperInvariant()] = "no existe o no se puede leer (" + ex.ErrorStatus + ")";
                }
            }
            return new JsonObject { ["values"] = valores, ["errors"] = errores };
        }

        /// <summary>params: name, value (texto, número o booleano).</summary>
        public static JsonObject Set(Document doc, JsonObject pars)
        {
            string nombre = pars["name"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(nombre))
                throw new ArgumentException("Falta 'name'.");
            if (pars["value"] == null)
                throw new ArgumentException("Falta 'value'.");
            if (Protegidas.Contains(nombre))
                throw new InvalidOperationException(
                    nombre.ToUpperInvariant() + " gobierna seguridad o qué se carga solo: " +
                    "la cambia una persona desde AutoCAD, no una tool.");

            object actual;
            try { actual = Application.GetSystemVariable(nombre); }
            catch (AcException ex)
            {
                throw new ArgumentException("La variable '" + nombre + "' no existe (" + ex.ErrorStatus + ").");
            }

            object nuevo = Convertir(pars["value"], actual, nombre);
            try
            {
                Application.SetSystemVariable(nombre, nuevo);
            }
            catch (AcException ex)
            {
                throw new InvalidOperationException(
                    "AutoCAD no dejó cambiar " + nombre.ToUpperInvariant() + " (" + ex.ErrorStatus +
                    "): puede ser de solo lectura o el valor no es válido.");
            }
            object leido = Application.GetSystemVariable(nombre);
            return new JsonObject
            {
                ["name"] = nombre.ToUpperInvariant(),
                ["previous"] = ToJson(actual),
                ["value"] = ToJson(leido),
            };
        }

        /// <summary>Lo que hay que mirar antes de mandarle trabajo a AutoCAD.</summary>
        public static JsonObject EditorState(Document doc, JsonObject pars)
        {
            var ed = doc.Editor;
            string cmd = SysVar("CMDNAMES");
            bool blockEditor = Convert.ToInt32(SysVarObj("BLOCKEDITOR") ?? 0) != 0;
            string refEdit = SysVar("REFEDITNAME");
            bool ocupado = !ed.IsQuiescent || blockEditor || !string.IsNullOrEmpty(refEdit);
            return new JsonObject
            {
                ["document"] = doc.Name,
                ["quiescent"] = ed.IsQuiescent,
                ["commandInProgress"] = cmd,
                ["blockEditorOpen"] = blockEditor,
                ["refEditName"] = refEdit,
                ["layout"] = SysVar("CTAB"),
                ["unsavedChanges"] = Convert.ToInt32(SysVarObj("DBMOD") ?? 0) != 0,
                ["busy"] = ocupado,
                ["note"] = ocupado
                    ? "AutoCAD no está libre (comando en curso, editor de bloques o edición en sitio): conviene esperar antes de mandarle trabajo."
                    : "AutoCAD está libre.",
            };
        }

        internal static object SysVarObj(string nombre)
        {
            try { return Application.GetSystemVariable(nombre); }
            catch (SysException) { return null; }
        }

        internal static string SysVar(string nombre)
        {
            var o = SysVarObj(nombre);
            return o == null ? "" : Convert.ToString(o);
        }

        private static JsonNode ToJson(object o)
        {
            switch (o)
            {
                case null: return null;
                case string s: return JsonValue.Create(s);
                case bool b: return JsonValue.Create(b);
                case short i16: return JsonValue.Create((int)i16);
                case int i32: return JsonValue.Create(i32);
                case long i64: return JsonValue.Create(i64);
                case double d: return JsonValue.Create(d);
                case float f: return JsonValue.Create((double)f);
                case Point3d p3: return new JsonArray(p3.X, p3.Y, p3.Z);
                case Point2d p2: return new JsonArray(p2.X, p2.Y);
                default: return JsonValue.Create(Convert.ToString(o));
            }
        }

        /// <summary>Lleva el valor recibido al tipo que ya tiene la variable
        /// (AutoCAD es estricto: un short no acepta un double).</summary>
        private static object Convertir(JsonNode valor, object actual, string nombre)
        {
            try
            {
                if (actual is string)
                    return valor.ToString().Trim('"');
                if (actual is short)
                    return Convert.ToInt16(ComoNumero(valor));
                if (actual is int)
                    return Convert.ToInt32(ComoNumero(valor));
                if (actual is long)
                    return Convert.ToInt64(ComoNumero(valor));
                if (actual is double)
                    return ComoNumero(valor);
                if (actual is Point3d)
                {
                    var a = valor as JsonArray;
                    if (a == null || a.Count != 3)
                        throw new ArgumentException("espera [x, y, z]");
                    return new Point3d(a[0].GetValue<double>(), a[1].GetValue<double>(), a[2].GetValue<double>());
                }
                if (actual is Point2d)
                {
                    var a = valor as JsonArray;
                    if (a == null || a.Count != 2)
                        throw new ArgumentException("espera [x, y]");
                    return new Point2d(a[0].GetValue<double>(), a[1].GetValue<double>());
                }
            }
            catch (SysException ex) when (ex is FormatException || ex is InvalidCastException
                                           || ex is OverflowException || ex is ArgumentException)
            {
                throw new ArgumentException(
                    "El valor no sirve para " + nombre.ToUpperInvariant() + " (" + ex.Message + "). " +
                    "Tipo actual: " + actual.GetType().Name + ".");
            }
            throw new ArgumentException(
                nombre.ToUpperInvariant() + " es de un tipo que no se puede cambiar desde acá (" +
                actual?.GetType().Name + ").");
        }

        private static double ComoNumero(JsonNode valor)
        {
            if (valor is JsonValue v)
            {
                if (v.TryGetValue<bool>(out var b)) return b ? 1 : 0;
                if (v.TryGetValue<double>(out var d)) return d;
                if (v.TryGetValue<string>(out var s))
                    return double.Parse(s, System.Globalization.CultureInfo.InvariantCulture);
            }
            throw new FormatException("no es un número");
        }
    }
}
