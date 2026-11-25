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

    /// <summary>
    /// Agrega «__Paso();» al principio del cuerpo de cada for / foreach / while / do del código de la IA, sin saltos
    /// de línea (las líneas de las excepciones siguen coincidiendo). No cubre recursión ni una sola llamada larga.
    /// </summary>
    internal sealed class Presupuesto : Microsoft.CodeAnalysis.CSharp.CSharpSyntaxRewriter
    {
        private readonly TextSpan _usuario;
        public Presupuesto(TextSpan usuario) { _usuario = usuario; }

        private static Microsoft.CodeAnalysis.CSharp.Syntax.BlockSyntax ConPaso(
            Microsoft.CodeAnalysis.CSharp.Syntax.StatementSyntax cuerpo)
        {
            var paso = SyntaxFactory.ParseStatement("__Paso();");
            return SyntaxFactory.Block(paso, cuerpo);
        }

        private bool Del(SyntaxNode n) => _usuario.Contains(n.Span);

        public override SyntaxNode VisitForStatement(Microsoft.CodeAnalysis.CSharp.Syntax.ForStatementSyntax node)
        {
            bool del = Del(node);
            var n = (Microsoft.CodeAnalysis.CSharp.Syntax.ForStatementSyntax)base.VisitForStatement(node);
            return del ? n.WithStatement(ConPaso(n.Statement)) : n;
        }

        public override SyntaxNode VisitForEachStatement(Microsoft.CodeAnalysis.CSharp.Syntax.ForEachStatementSyntax node)
        {
            bool del = Del(node);
            var n = (Microsoft.CodeAnalysis.CSharp.Syntax.ForEachStatementSyntax)base.VisitForEachStatement(node);
            return del ? n.WithStatement(ConPaso(n.Statement)) : n;
        }

        public override SyntaxNode VisitForEachVariableStatement(Microsoft.CodeAnalysis.CSharp.Syntax.ForEachVariableStatementSyntax node)
        {
            bool del = Del(node);
            var n = (Microsoft.CodeAnalysis.CSharp.Syntax.ForEachVariableStatementSyntax)base.VisitForEachVariableStatement(node);
            return del ? n.WithStatement(ConPaso(n.Statement)) : n;
        }

        public override SyntaxNode VisitWhileStatement(Microsoft.CodeAnalysis.CSharp.Syntax.WhileStatementSyntax node)
        {
            bool del = Del(node);
            var n = (Microsoft.CodeAnalysis.CSharp.Syntax.WhileStatementSyntax)base.VisitWhileStatement(node);
            return del ? n.WithStatement(ConPaso(n.Statement)) : n;
        }

        public override SyntaxNode VisitDoStatement(Microsoft.CodeAnalysis.CSharp.Syntax.DoStatementSyntax node)
        {
            bool del = Del(node);
            var n = (Microsoft.CodeAnalysis.CSharp.Syntax.DoStatementSyntax)base.VisitDoStatement(node);
            return del ? n.WithStatement(ConPaso(n.Statement)) : n;
        }

        // goto hacia atrás también arma un bucle: se le pone el chequeo antes de saltar.
        public override SyntaxNode VisitGotoStatement(Microsoft.CodeAnalysis.CSharp.Syntax.GotoStatementSyntax node)
        {
            bool del = Del(node);
            var n = base.VisitGotoStatement(node);
            if (!del || !(node.Parent is Microsoft.CodeAnalysis.CSharp.Syntax.BlockSyntax)) return n;
            return SyntaxFactory.Block(SyntaxFactory.ParseStatement("__Paso();"), (Microsoft.CodeAnalysis.CSharp.Syntax.StatementSyntax)n);
        }
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
                // Se emite una copia con un chequeo de tiempo al principio de cada bucle (__Paso de ScriptBase).
                // Los errores y el filtro ya se vieron sobre el código ORIGINAL, así que la IA no ve nada de esto.
                var conPresupuesto = arbol.WithRootAndOptions(new Presupuesto(userSpan).Visit(arbol.GetRoot()), arbol.Options);
                var compilacionEmit = compilacion.ReplaceSyntaxTree(arbol, conPresupuesto);
                var emitido = compilacionEmit.Emit(pe, pdb,
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
#if NET8_0_OR_GREATER
                // AutoCAD 2027 carga en el proceso archivos que no son assemblies administrados
                // (slidelib.exe): Roslyn falla entero si uno de ellos va como referencia. Solo en el
                // target de 2027, para no tocar el comportamiento de las versiones ya probadas.
                try { System.Reflection.AssemblyName.GetAssemblyName(ruta); }
                catch (Exception) { return; }
#endif
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
