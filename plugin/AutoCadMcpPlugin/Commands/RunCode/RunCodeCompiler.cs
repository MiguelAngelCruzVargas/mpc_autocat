using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Emit;
using Microsoft.CodeAnalysis.Text;

namespace AutoCadMcpPlugin.Commands.RunCode
{
    /// <summary>Un error de compilación, en coordenadas del código de la IA.</summary>
    internal sealed class CompileError
    {
        public int Line;
        public int Column;
        public string Message;
        public string Severity;
        public string Id;
    }

    /// <summary>
    /// Lo que sale de compilar. NO expone ningún tipo de Roslyn a propósito:
    /// RunCodeCommand lo usa sin referenciar Microsoft.CodeAnalysis, así que si
    /// Roslyn no carga dentro de AutoCAD la falla aparece al llamar Compile(),
    /// donde se puede atrapar, y no al JIT de RunCodeCommand, donde no.
    /// </summary>
    internal sealed class CompileOutcome
    {
        public Type ScriptType;
        public List<CompileError> Errors = new List<CompileError>();
        public List<Blocked> Blocked = new List<Blocked>();
        public bool FromCache;
    }

    internal static class RunCodeCompiler
    {
        /// <summary>
        /// La plantilla. '#line 1' hace que Roslyn informe los errores con la
        /// línea del código de la IA, no la de la plantilla: es lo que le
        /// permite corregirse sola. El 'return null' final evita exigirle un
        /// return; si ella pone uno antes, solo queda código inalcanzable.
        /// </summary>
        private const string Prefijo =
            "using System;\n" +
            "using System.Collections.Generic;\n" +
            "using System.Linq;\n" +
            "using System.Text;\n" +
            "using Autodesk.AutoCAD.ApplicationServices;\n" +
            "using Autodesk.AutoCAD.DatabaseServices;\n" +
            "using Autodesk.AutoCAD.EditorInput;\n" +
            "using Autodesk.AutoCAD.Geometry;\n" +
            "using Autodesk.AutoCAD.Colors;\n" +
            "using Application = Autodesk.AutoCAD.ApplicationServices.Application;\n" +
            "namespace AutoCadMcpScript {\n" +
            "public sealed class Script : AutoCadMcpPlugin.Commands.RunCode.ScriptBase {\n" +
            "public override object Run() {\n" +
            "#line 1 \"codigo.cs\"\n";

        private const string Sufijo =
            "\n#line hidden\n" +
            ";return null;\n}\n}\n}\n";

        private static readonly Dictionary<string, Type> Cache = new Dictionary<string, Type>(StringComparer.Ordinal);
        private static readonly object CacheLock = new object();
        private static int _contador;

        public static CompileOutcome Compile(string code, bool permitirSistema)
        {
            string clave = Hash(code) + (permitirSistema ? ":sistema" : ":filtrado");
            lock (CacheLock)
            {
                if (Cache.TryGetValue(clave, out var enCache))
                    return new CompileOutcome { ScriptType = enCache, FromCache = true };
            }

            var fuente = Prefijo + code + Sufijo;
            var userSpan = new TextSpan(Prefijo.Length, code.Length);
            var arbol = CSharpSyntaxTree.ParseText(
                SourceText.From(fuente, Encoding.UTF8),
                new CSharpParseOptions(LanguageVersion.Latest),
                path: "codigo.cs");

            var compilacion = CSharpCompilation.Create(
                "AutoCadMcpScript_" + clave.Substring(0, 12) + "_" + (++_contador),
                new[] { arbol },
                Referencias(),
                new CSharpCompilationOptions(
                    OutputKind.DynamicallyLinkedLibrary,
                    optimizationLevel: OptimizationLevel.Debug,
                    allowUnsafe: false));

            var salida = new CompileOutcome();
            foreach (var d in compilacion.GetDiagnostics())
            {
                if (d.Severity != DiagnosticSeverity.Error)
                    continue;
                var pos = d.Location.GetMappedLineSpan().StartLinePosition;
                salida.Errors.Add(new CompileError
                {
                    Line = pos.Line + 1,
                    Column = pos.Character + 1,
                    Message = d.GetMessage(),
                    Severity = "error",
                    Id = d.Id,
                });
            }
            if (salida.Errors.Count > 0)
                return salida;

            if (!permitirSistema)
            {
                var modelo = compilacion.GetSemanticModel(arbol);
                salida.Blocked = RunCodeFilter.Check(modelo, arbol.GetRoot(), userSpan);
                if (salida.Blocked.Count > 0)
                    return salida;
            }

            using (var pe = new MemoryStream())
            using (var pdb = new MemoryStream())
            {
                // Con el PDB, una excepción en el código de la IA trae
                // "codigo.cs:línea N" en el stack: se le puede decir dónde falló.
                var emitido = compilacion.Emit(pe, pdb,
                    options: new EmitOptions(debugInformationFormat: DebugInformationFormat.PortablePdb));
                if (!emitido.Success)
                {
                    foreach (var d in emitido.Diagnostics.Where(x => x.Severity == DiagnosticSeverity.Error))
                    {
                        var pos = d.Location.GetMappedLineSpan().StartLinePosition;
                        salida.Errors.Add(new CompileError
                        {
                            Line = pos.Line + 1, Column = pos.Character + 1,
                            Message = d.GetMessage(), Severity = "error", Id = d.Id,
                        });
                    }
                    return salida;
                }
                var asm = Assembly.Load(pe.ToArray(), pdb.ToArray());
                salida.ScriptType = asm.GetType("AutoCadMcpScript.Script", throwOnError: true);
            }

            lock (CacheLock)
                Cache[clave] = salida.ScriptType;
            return salida;
        }

        /// <summary>
        /// Contra qué se compila: lo que ya está cargado en acad.exe. Así el
        /// código ve exactamente la API de la versión de AutoCAD instalada, y
        /// no hace falta saber dónde están sus DLL. Se deduplica por nombre:
        /// dos versiones del mismo assembly hacen fallar la compilación.
        /// </summary>
        private static List<MetadataReference> Referencias()
        {
            var porNombre = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            void Sumar(string ruta)
            {
                if (string.IsNullOrEmpty(ruta) || !File.Exists(ruta))
                    return;
                var nombre = Path.GetFileNameWithoutExtension(ruta);
                if (!porNombre.ContainsKey(nombre))
                    porNombre[nombre] = ruta;
            }

            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (asm.IsDynamic)
                    continue;
                string ruta;
                try { ruta = asm.Location; }
                catch (Exception) { continue; }
                Sumar(ruta);
            }

            // Fachadas que los assemblies de AutoCAD o del plugin pueden pedir
            // al resolver tipos (netstandard, System.Runtime).
            var dirRuntime = System.Runtime.InteropServices.RuntimeEnvironment.GetRuntimeDirectory();
            Sumar(Path.Combine(dirRuntime, "netstandard.dll"));
            Sumar(Path.Combine(dirRuntime, "Facades", "netstandard.dll"));
            Sumar(Path.Combine(dirRuntime, "Facades", "System.Runtime.dll"));

            if (AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") is string tpa)
            {
                foreach (var ruta in tpa.Split(Path.PathSeparator))
                    Sumar(ruta);
            }

            return porNombre.Values
                .Select(r => (MetadataReference)MetadataReference.CreateFromFile(r))
                .ToList();
        }

        private static string Hash(string texto)
        {
            using (var sha = SHA256.Create())
            {
                var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(Prefijo + texto + Sufijo));
                var sb = new StringBuilder(bytes.Length * 2);
                foreach (var b in bytes)
                    sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }
    }
}
