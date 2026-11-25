using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;

namespace AutoCadMcpPlugin.Commands.RunCode
{
    /// <summary>
    /// Base de la clase que se arma con el código que manda la IA.
    ///
    /// Es pública porque la clase generada vive en OTRO assembly (el que se
    /// compila en memoria) y tiene que poder heredar de esta. Lo que la IA
    /// usa son los miembros protegidos; Init y Output son internos, así que
    /// desde el código generado no se pueden tocar.
    /// </summary>
    public abstract class ScriptBase
    {
        private const int MaxSalida = 200_000;

        protected Document doc;
        protected Database db;
        protected Editor ed;
        protected Transaction tr;
        /// <summary>El espacio ACTIVO (modelo o el layout actual), abierto para escritura.</summary>
        protected BlockTableRecord space;

        private readonly StringBuilder _salida = new StringBuilder();
        private bool _recortada;

        /// <summary>Tiempo máximo de un run_code (ACAD_MCP_RUN_CODE_TIMEOUT, 45 s por omisión; menor que el del socket).</summary>
        internal static readonly int SegundosMaximos = LeerSegundos();

        internal static string MensajeTiempo =>
            "run_code superó su tiempo máximo (" + SegundosMaximos + " s) dentro de un bucle y se detuvo: no se aplicó nada.";

        private static int LeerSegundos()
        {
            var raw = System.Environment.GetEnvironmentVariable("ACAD_MCP_RUN_CODE_TIMEOUT");
            return int.TryParse(raw, out var n) && n > 0 ? n : 45;
        }

        private readonly System.Diagnostics.Stopwatch _reloj = new System.Diagnostics.Stopwatch();
        private bool _agotado;

        internal bool TiempoAgotado => _agotado;

        /// <summary>
        /// Lo inserta el compilador al principio de CADA bucle del código de la IA (RunCodeCompiler.Presupuesto).
        /// Pasado el tiempo tira una excepción, y la vuelve a tirar en cada vuelta siguiente aunque el código la
        /// atrape; si aun así Run termina, Ejecutar lo da por fallido y descarta la transacción.
        /// </summary>
        protected void __Paso()
        {
            if (_agotado || _reloj.ElapsedMilliseconds > SegundosMaximos * 1000L)
            {
                _agotado = true;
                throw new System.TimeoutException(MensajeTiempo);
            }
        }

        internal void Init(Document documento, Transaction transaccion)
        {
            _reloj.Restart();
            doc = documento;
            db = documento.Database;
            ed = documento.Editor;
            tr = transaccion;
            space = SpaceHelper.Current(db, transaccion);
        }

        internal string Output => _recortada
            ? _salida + "\n[... salida recortada a " + MaxSalida + " caracteres]"
            : _salida.ToString();

        /// <summary>ObjectId a partir del handle hex que devuelven las tools.</summary>
        protected ObjectId H(string handle) => HandleHelper.GetObjectId(db, handle);

        /// <summary>
        /// Agrega la entidad al espacio activo y a la transacción, y devuelve su
        /// handle. Olvidarse de AddNewlyCreatedDBObject deja la entidad a medio
        /// registrar: es el error más común al usar la API a mano.
        /// </summary>
        protected string Add(Entity entidad)
        {
            var id = space.AppendEntity(entidad);
            tr.AddNewlyCreatedDBObject(entidad, true);
            return id.Handle.ToString();
        }

        /// <summary>Texto que vuelve en 'output'.</summary>
        protected void Print(object valor)
        {
            if (_recortada)
                return;
            _salida.AppendLine(valor?.ToString() ?? "null");
            if (_salida.Length > MaxSalida)
            {
                _salida.Length = MaxSalida;
                _recortada = true;
            }
        }

        public abstract object Run();
    }
}
