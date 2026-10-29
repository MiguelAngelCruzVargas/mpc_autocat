using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using AutoCadMcpPlugin.Chat;

namespace ChatHarness
{
    /// <summary>Un «AutoCAD» inventado: dibujo, selección y tema fijos.</summary>
    internal sealed class ContextoFalso : IContextoCad
    {
        public bool Claro;
        public int Sel = 3;
        public string NombreDibujo => "Portico_Barda_Mixtan.dwg";
        public int Seleccionados => Sel;
        public bool TemaClaro => Claro;
        public event Action Cambio;
        public string DescribirSeleccion(int max) =>
            "[Contexto de AutoCAD] Dibujo activo: " + NombreDibujo + ". La persona tiene seleccionadas 3 entidad(es). Si dice «esto», se refiere a:\n" +
            "- Polyline handle=2A capa=MUROS\n- Line handle=2B capa=EJES\n- Circle handle=2C capa=MOBILIARIO";
        public void Disparar() => Cambio?.Invoke();
    }

    internal static class Program
    {
        private static string Arg(string[] a, string nombre, string defecto = null)
        {
            var i = Array.IndexOf(a, nombre);
            return i >= 0 && i + 1 < a.Length ? a[i + 1] : defecto;
        }

        [STAThread]
        private static int Main(string[] args)
        {
            var url = Arg(args, "--url", "http://127.0.0.1:8780");
            var png = Arg(args, "--png");
            var enviar = Arg(args, "--enviar");
            var proveedor = Arg(args, "--proveedor");
            var espera = int.Parse(Arg(args, "--espera", "10"));
            var ancho = int.Parse(Arg(args, "--ancho", "420"));
            var alto = int.Parse(Arg(args, "--alto", "720"));
            var claro = args.Contains("--claro");
            var adjuntar = args.Contains("--adjuntar");

            var app = new Application();
            var ctx = new ContextoFalso { Claro = claro };
            var panel = new ChatPanel(ctx, () => Task.FromResult<(string, string)>((url, null)));
            var ventana = new Window { Width = ancho, Height = alto, Content = panel, Title = "Chat nativo (prueba)" };
            int codigo = 0;
            ventana.ContentRendered += async (s, e) =>
            {
                try
                {
                    await Task.Delay(300);
                    await panel.Inicio;
                    if (proveedor != null) await panel.ElegirProveedorPorIdAsync(proveedor);
                    var perfil = Arg(args, "--perfil");
                    if (perfil != null) panel.ElegirPerfil(perfil);
                    if (args.Contains("--ajustes")) panel.AbrirAjustes();
                    if (args.Contains("--historial")) panel.AbrirHistorialPantalla();
                    if (args.Contains("--abajo")) { await Task.Delay(400); panel.BajarAjustes(); await Task.Delay(300); }
                    if (enviar != null)
                    {
                        if (adjuntar) { ctx.Disparar(); panel.AdjuntarSeleccion = true; }
                        await panel.EnviarTextoAsync(enviar);
                    }
                    var limite = DateTime.UtcNow.AddSeconds(espera);
                    while ((panel.Trabajando || DateTime.UtcNow < limite) && DateTime.UtcNow < limite.AddSeconds(90))
                    {
                        await Task.Delay(500);
                        if (!panel.Trabajando && DateTime.UtcNow >= limite) break;
                    }
                    await Task.Delay(800);
                    if (png != null) { Capturar(panel, png); File.WriteAllText(png + ".ok.txt", "capturado"); }
                }
                catch (Exception ex) { Console.Error.WriteLine(ex); if (png != null) File.WriteAllText(png + ".error.txt", ex.ToString()); codigo = 1; }
                finally { app.Shutdown(); }
            };
            app.Run(ventana);
            return codigo;
        }

        private static void Capturar(FrameworkElement el, string ruta)
        {
            el.UpdateLayout();
            int w = (int)Math.Max(1, el.ActualWidth), h = (int)Math.Max(1, el.ActualHeight);
            var rtb = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
            rtb.Render(el);
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(rtb));
            using (var f = File.Create(ruta)) enc.Save(f);
        }
    }
}
