using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>Lo que el panel necesita saber de AutoCAD. Lo implementa ContextoCad; las pruebas usan uno de mentira.</summary>
    internal interface IContextoCad
    {
        string NombreDibujo { get; }
        int Seleccionados { get; }
        string DescribirSeleccion(int max);
        bool TemaClaro { get; }
        event Action Cambio;
    }

    internal sealed class ProveedorItem
    {
        public string Id, ModeloSugerido, Detalle;
        public bool Clave, Puente, Vivo;
        public string Nombre =>
            Vivo ? "En vivo · tu agente" : (Id.ToUpperInvariant() + (Clave || Puente ? "" : " · sin clave"));
    }

    /// <summary>
    /// El chat de AutoCAD hecho como panel nativo (WPF), no como una página web. El cerebro (proveedores, herramientas,
    /// permisos, costo, modo «En vivo») sigue en el servidor Python y se le habla por HTTP local (ChatCliente); lo de
    /// aquí es la cara y lo que solo AutoCAD sabe: el dibujo activo, la selección y el tema.
    /// </summary>
    internal sealed class ChatPanel : UserControl
    {
        private readonly IContextoCad _ctx;
        private readonly Func<Task<(string url, string problema)>> _asegurar;
        private readonly ChatTema _t;
        private ChatCliente _cli;
        private AgenteNativo _agente;       // el bucle del agente, en C# (los puentes a CLIs siguen por el servidor)

        // controles
        private readonly Button _provBtn = new Button(), _modeloBtn = new Button(), _ajustesBtn = new Button(), _nuevaBtn = new Button();
        private readonly TextBox _modelo = new TextBox();
        private readonly ScrollViewer _scroll = new ScrollViewer();
        private readonly StackPanel _lista = new StackPanel();
        private readonly ScrollViewer _vivoScroll = new ScrollViewer();
        private readonly StackPanel _vivoLista = new StackPanel();
        private readonly TextBlock _vivoEstado = new TextBlock();
        private readonly TextBox _vivoAyuda = new TextBox();
        private readonly Grid _ajustes = new Grid();
        private readonly TextBlock _ctxTexto = new TextBlock();
        private readonly CheckBox _adjSel = new CheckBox();
        private readonly TextBlock _estado = new TextBlock();
        // Lo que el agente está haciendo ahora («Pensando…», «Dibujando círculo…»), con puntos que se mueven: en vez de enseñar las tripas.
        private readonly Border _actividad = new Border { Visibility = Visibility.Collapsed };
        private readonly TextBlock _actividadTxt = new TextBlock();
        private readonly Border _actividadLinea = new Border { Height = 2 };       // la línea que se va trazando mientras el agente trabaja
        private ScaleTransform _trazo;
        private Style _estiloFantasma, _estiloCajetin;
        private int _nPaso;
        private bool _primerAsistente = true;
        private DispatcherTimer _animTimer;
        private string _fase = "";
        private int _puntos;
        private readonly TextBox _entrada = new TextBox();
        private readonly TextBlock _placeholder = new TextBlock();
        private readonly Button _enviar = new Button();
        private readonly PasswordBox _clave = new PasswordBox();
        private readonly TextBlock _claveEstado = new TextBlock();
        private readonly CheckBox _reglas = new CheckBox();
        private readonly Slider _temp = new Slider();
        // permisos, tope de gasto y licencia (ajustes)
        private string _modoPermisos = "destructivo";
        private readonly StackPanel _listaPermisos = new StackPanel();
        private readonly TextBox _tope = new TextBox();
        private readonly StackPanel _licSeccion = new StackPanel { Visibility = Visibility.Collapsed };
        private readonly TextBlock _licEstado = new TextBlock();
        private readonly TextBox _licClave = new TextBox();
        private bool _licObligatoria, _licValida = true;
        private readonly StackPanel _listaProv = new StackPanel(), _listaModelos = new StackPanel(), _listaPerfiles = new StackPanel(), _seccionApi = new StackPanel();
        private readonly Grid _entradaFila = new Grid();
        private Border _vivoAviso;
        private readonly Button _notaBtn = new Button();
        private bool _notaAbierta;

        // estado
        private readonly List<ProveedorItem> _provs = new List<ProveedorItem>();
        private readonly Dictionary<string, string> _modelos = new Dictionary<string, string>();
        private readonly List<(string id, int tools)> _perfiles = new List<(string, int)>();
        private string _perfil = "arquitectura";
        private ProveedorItem _prov;
        private CancellationTokenSource _cts;
        private bool _trabajando;
        private bool _hayConversacion;
        private readonly Dictionary<string, Queue<TarjetaTool>> _pendientes = new Dictionary<string, Queue<TarjetaTool>>();
        private int _tokens, _vueltas;
        private double _costo;
        private DispatcherTimer _vivoTimer;
        private long _posAct, _posBan;
        private bool _vivoPrimera = true, _vivoOcupado, _vivoActividad;
        private int _vivoAbiertas;
        private double _vivoUltima;
        private readonly Dictionary<string, TarjetaTool> _vivoTarjetas = new Dictionary<string, TarjetaTool>();

        public ChatPanel(IContextoCad ctx, Func<Task<(string url, string problema)>> asegurar)
        {
            _ctx = ctx;
            _asegurar = asegurar;
            _t = ChatTema.Crear(ctx.TemaClaro);
            FontFamily = new FontFamily("Segoe UI");
            FontSize = 13;
            Background = _t.Fondo;
            Foreground = _t.Texto;
            Resources.Add(typeof(Button), _t.EstiloBoton());
            Resources.Add(typeof(System.Windows.Controls.Primitives.ScrollBar), ChatEstilos.BarraDesplazamiento(_t));
            Resources.Add(typeof(CheckBox), ChatEstilos.Casilla(_t));
            Content = Construir();
            _ctx.Cambio += () => Dispatcher.BeginInvoke(new Action(ActualizarContexto));
            Loaded += async (s, e) => { if (_cli == null) { Inicio = IniciarAsync(); await Inicio.ConfigureAwait(true); } };
        }

        // Ganchos para el programa de prueba (plugin/ChatHarness): mismas rutas que usa la persona, sin teclear.
        internal Task Inicio = Task.CompletedTask;
        internal bool Trabajando => _trabajando;
        internal void ElegirPerfil(string id) { _perfil = id; }
        internal bool AdjuntarSeleccion { set { _adjSel.IsChecked = value; } }
        internal Task EnviarTextoAsync(string texto) { _entrada.Text = texto; return EnviarAsync(); }
        internal Task ElegirProveedorPorIdAsync(string id)
        {
            var p = _provs.FirstOrDefault(x => x.Id == id);
            return p == null ? Task.CompletedTask : ElegirProveedorAsync(p, false);
        }

        // ------------------------------------------------------------------------------------------ construcción

        private Grid Construir()
        {
            var raiz = new Grid { Background = _t.Fondo };
            for (int i = 0; i < 5; i++) raiz.RowDefinitions.Add(new RowDefinition { Height = i == 2 ? new GridLength(1, GridUnitType.Star) : GridLength.Auto });

            // cabecera: qué IA está activa (nombre y modelo COMPLETOS), ajustes y conversación nueva.
            // No hay menús desplegables: los menús emergentes de WPF no se abren bien dentro de una paleta de AutoCAD,
            // así que todo lo que se elige vive en la pantalla de configuración (el botón de la tuerca).
            var cab = new Grid { Margin = new Thickness(8, 8, 8, 8) };
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            _estiloFantasma = ChatEstilos.Fantasma(_t); _estiloCajetin = ChatEstilos.Cajetin(_t);
            _provBtn.Style = _estiloCajetin; _ajustesBtn.Style = _estiloCajetin; _nuevaBtn.Style = _estiloCajetin;
            _provBtn.HorizontalContentAlignment = HorizontalAlignment.Stretch; _provBtn.Padding = new Thickness(9, 5, 9, 6);
            _provBtn.Click += (s, e) => AbrirAjustes();
            ActualizarChip();
            _ajustesBtn.Content = Icono("\uE713"); _ajustesBtn.ToolTip = "Configuración"; _ajustesBtn.Margin = new Thickness(6, 0, 0, 0); _ajustesBtn.Width = 38;
            _ajustesBtn.Click += (s, e) => { if (_ajustes.Visibility == Visibility.Visible) _ajustes.Visibility = Visibility.Collapsed; else AbrirAjustes(); };
            Grid.SetColumn(_ajustesBtn, 1);
            _nuevaBtn.Content = Icono("\uE710"); _nuevaBtn.ToolTip = "Conversación nueva"; _nuevaBtn.Margin = new Thickness(6, 0, 0, 0); _nuevaBtn.Width = 38;
            _nuevaBtn.Click += async (s, e) => await NuevaAsync().ConfigureAwait(true);
            Grid.SetColumn(_nuevaBtn, 2);
            cab.Children.Add(_provBtn); cab.Children.Add(_ajustesBtn); cab.Children.Add(_nuevaBtn);
            var cabBorde = new Border { Background = _t.Panel, Child = cab };
            Grid.SetRow(cabBorde, 0); raiz.Children.Add(cabBorde);

            // fila de contexto de AutoCAD: dibujo activo y selección
            var ctxFila = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(12, 5, 8, 5) };
            _ctxTexto.Foreground = _t.Texto; _ctxTexto.FontFamily = Mono; _ctxTexto.FontSize = 10.5; _ctxTexto.VerticalAlignment = VerticalAlignment.Center;
            _ctxTexto.TextTrimming = TextTrimming.CharacterEllipsis;
            _adjSel.Content = "adjuntar selección"; _adjSel.Foreground = _t.Texto; _adjSel.FontSize = 11; _adjSel.Margin = new Thickness(12, 0, 0, 0);
            _adjSel.VerticalAlignment = VerticalAlignment.Center; _adjSel.Visibility = Visibility.Collapsed;
            _adjSel.ToolTip = "Le manda al agente los handles y tipos de lo que tienes seleccionado en el dibujo";
            ctxFila.Children.Add(_ctxTexto);
            ctxFila.Children.Add(_adjSel);
            var ctxBorde = new Border { BorderBrush = _t.Borde, BorderThickness = new Thickness(0, 1, 0, 1), Child = ctxFila };
            Grid.SetRow(ctxBorde, 1); raiz.Children.Add(ctxBorde);

            // contenido: conversación o vista «en vivo», y los ajustes encima
            var contenido = new Grid();
            _scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            _scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
            _lista.Margin = new Thickness(12, 2, 12, 10);
            _scroll.Content = _lista;
            contenido.Children.Add(_scroll);

            var vivo = new Grid { Visibility = Visibility.Collapsed, Tag = "vivo" };
            vivo.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            vivo.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            _vivoEstado.Foreground = _t.Suave; _vivoEstado.Margin = new Thickness(10, 2, 6, 4); _vivoEstado.Text = "Esperando a tu agente…";
            vivo.Children.Add(_vivoEstado);
            _vivoScroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            _vivoScroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
            var vivoCont = new StackPanel { Margin = new Thickness(6, 0, 6, 6) };
            _vivoLista.Margin = new Thickness(0);
            _vivoAyuda.IsReadOnly = true; _vivoAyuda.TextWrapping = TextWrapping.Wrap; _vivoAyuda.Background = _t.Codigo; _vivoAyuda.Foreground = _t.Suave;
            _vivoAyuda.BorderThickness = new Thickness(0); _vivoAyuda.FontSize = 11; _vivoAyuda.Padding = new Thickness(6); _vivoAyuda.Margin = new Thickness(0, 6, 0, 0);
            _vivoAyuda.Text = "Conecta tu agente una vez a este servidor de AutoCAD (el comando exacto sale aquí cuando el servidor arranca).";
            vivoCont.Children.Add(_vivoLista); vivoCont.Children.Add(_vivoAyuda);
            _vivoScroll.Content = vivoCont;
            Grid.SetRow(_vivoScroll, 1); vivo.Children.Add(_vivoScroll);
            contenido.Children.Add(vivo);

            ConstruirAjustes();
            Grid.SetRow(contenido, 2); raiz.Children.Add(contenido);

            // estado
            _estado.Foreground = _t.Suave; _estado.FontFamily = Mono; _estado.FontSize = 10; _estado.Margin = new Thickness(12, 6, 8, 0); _estado.TextTrimming = TextTrimming.CharacterEllipsis;
            _actividadTxt.Foreground = _t.Acento; _actividadTxt.FontFamily = Mono; _actividadTxt.FontSize = 11.5; _actividadTxt.TextTrimming = TextTrimming.CharacterEllipsis;
            _trazo = new ScaleTransform(0, 1);
            _actividadLinea.Background = _t.Acento; _actividadLinea.RenderTransformOrigin = new Point(0, 0.5); _actividadLinea.RenderTransform = _trazo;
            var pista = new Grid { Height = 2, Margin = new Thickness(0, 5, 0, 0), Background = _t.Borde, ClipToBounds = true };
            pista.Children.Add(_actividadLinea);
            var pilaActividad = new StackPanel();
            pilaActividad.Children.Add(_actividadTxt); pilaActividad.Children.Add(pista);
            _actividad.Child = pilaActividad; _actividad.Margin = new Thickness(12, 9, 12, 2);
            _animTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(420) };
            _animTimer.Tick += (s, e) => { _puntos = (_puntos + 1) % 4; _actividadTxt.Text = _fase + new string('.', _puntos); };


            // entrada
            ConstruirAvisoVivo();
            var ent = _entradaFila; ent.Margin = new Thickness(0);
            ent.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            ent.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            ent.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            // como la línea de comandos de AutoCAD: un indicador a la izquierda y el texto en un recuadro de filo fino
            var indicador = new TextBlock { Text = "›", FontFamily = Mono, FontSize = 18, Foreground = _t.Acento, Margin = new Thickness(10, 3, 0, 0), VerticalAlignment = VerticalAlignment.Top };
            var caja = new Grid();
            Grid.SetColumn(caja, 1);
            EstilizarTexto(_entrada);
            _entrada.AcceptsReturn = true; _entrada.TextWrapping = TextWrapping.Wrap; _entrada.MinHeight = 36; _entrada.MaxHeight = 120;
            _entrada.VerticalScrollBarVisibility = ScrollBarVisibility.Auto; _entrada.Padding = new Thickness(6, 8, 6, 5);
            _entrada.Background = Brushes.Transparent; _entrada.BorderThickness = new Thickness(0);
            _entrada.PreviewKeyDown += async (s, e) =>
            {
                if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Shift) == 0) { e.Handled = true; await EnviarAsync().ConfigureAwait(true); }
            };
            _entrada.TextChanged += (s, e) => _placeholder.Visibility = _entrada.Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
            _placeholder.Text = "Escribe tu instrucción…"; _placeholder.Foreground = _t.Suave; _placeholder.IsHitTestVisible = false;
            _placeholder.Margin = new Thickness(8, 9, 0, 0); _placeholder.VerticalAlignment = VerticalAlignment.Top;
            caja.Children.Add(_entrada); caja.Children.Add(_placeholder);
            _enviar.Content = "ENVIAR"; _enviar.FontFamily = Mono; _enviar.FontSize = 10.5; _enviar.FontWeight = FontWeights.Bold;
            _enviar.Margin = new Thickness(4, 4, 4, 4); _enviar.Padding = new Thickness(12, 4, 12, 4);
            _enviar.Background = _t.Acento; _enviar.Foreground = _t.AcentoTexto; _enviar.BorderBrush = _t.Acento; _enviar.VerticalAlignment = VerticalAlignment.Stretch;
            _enviar.Click += async (s, e) => { if (_trabajando) Detener(); else await EnviarAsync().ConfigureAwait(true); };
            Grid.SetColumn(_enviar, 2);
            ent.Children.Add(indicador); ent.Children.Add(caja); ent.Children.Add(_enviar);
            var entBorde = new Border { Background = _t.Fondo, BorderBrush = _t.Borde, BorderThickness = new Thickness(1), Margin = new Thickness(10, 8, 10, 10), Child = ent };
            var pie = new Border { BorderBrush = _t.Borde, BorderThickness = new Thickness(0, 1, 0, 0), Background = _t.Panel, Child = new StackPanel { Children = { _actividad, _estado, _vivoAviso, entBorde } } };
            Grid.SetRow(pie, 3); Grid.SetRowSpan(pie, 2); raiz.Children.Add(pie);
            // la configuración cubre todo el panel (dibujo, conversación y caja de escribir): es una pantalla aparte
            Grid.SetRow(_ajustes, 1); Grid.SetRowSpan(_ajustes, 4); Panel.SetZIndex(_ajustes, 10); raiz.Children.Add(_ajustes);

            MostrarSugerencias();
            ActualizarContexto();
            return raiz;
        }

        private void EstilizarTexto(TextBox tb)
        {
            tb.Background = _t.Tarjeta; tb.Foreground = _t.Texto; tb.BorderBrush = _t.Borde; tb.CaretBrush = _t.Texto;
            tb.Padding = new Thickness(4, 3, 4, 3); tb.VerticalContentAlignment = VerticalAlignment.Center;
        }

        // Un glifo de la fuente de iconos de Windows (el ⚙ de texto sale como una flor).
        private static TextBlock Icono(string glifo, double tam = 15) =>
            new TextBlock { Text = glifo, FontFamily = new FontFamily("Segoe Fluent Icons, Segoe MDL2 Assets"), FontSize = tam, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center };

        private string TextoPerfil()
        {
            var n = _perfiles.Where(x => x.id == _perfil).Select(x => x.tools).FirstOrDefault();
            return "Especialidad: " + _perfil + (n > 0 ? " · " + n + " herramientas" : "");
        }

        private static readonly Dictionary<string, string> NombresIa = new Dictionary<string, string>
        {
            ["groq"] = "Groq", ["openrouter"] = "OpenRouter", ["openai"] = "OpenAI", ["deepseek"] = "DeepSeek", ["together"] = "Together",
            ["local"] = "Local", ["anthropic"] = "Claude", ["en-vivo"] = "En vivo",
        };

        private static readonly FontFamily Mono = new FontFamily("Consolas");

        /// <summary>Letras con un hilo de aire entre ellas: los rótulos de un plano van «abiertos».</summary>
        private static string Espaciado(string s) => string.Join("\u200A", s.ToCharArray().Select(c => c.ToString()));

        private void ActualizarChip()
        {
            // El cajetín: dos renglones rotulados, como el cuadro de rotulación de un plano.
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            string modelo = _modelo.Text.Trim();
            string ia = _prov == null ? "" : NombresIa.TryGetValue(_prov.Id, out var bonito) ? bonito : _prov.Nombre.Replace(" · sin clave", "");
            var esp = string.IsNullOrEmpty(_perfil) ? "" : char.ToUpperInvariant(_perfil[0]) + _perfil.Substring(1);
            string valor0 = _prov == null ? "elegir con qué IA trabajar" : _prov.Vivo ? "tu agente, en vivo" : (modelo.Length > 0 ? modelo : ia);
            string valor1 = _prov == null ? "" : _prov.Vivo ? "aquí ves lo que hace" : ia + (esp.Length > 0 ? "  ·  " + esp : "");
            var l0 = new TextBlock { Text = Espaciado("MODELO"), FontFamily = Mono, FontSize = 8.5, Foreground = _t.Suave, VerticalAlignment = VerticalAlignment.Center };
            var v0 = new TextBlock { Text = valor0, FontFamily = Mono, FontSize = 12, FontWeight = FontWeights.SemiBold, Foreground = _t.Texto, TextTrimming = TextTrimming.CharacterEllipsis };
            var l1 = new TextBlock { Text = Espaciado("IA"), FontFamily = Mono, FontSize = 8.5, Foreground = _t.Suave, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 3, 0, 0) };
            var v1 = new TextBlock { Text = valor1, FontFamily = Mono, FontSize = 10.5, Foreground = _t.Suave, TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 3, 0, 0) };
            Grid.SetRow(l1, 1); Grid.SetColumn(v0, 1); Grid.SetColumn(v1, 1); Grid.SetRow(v1, 1);
            var flecha = Icono("\uE70D", 9); flecha.Foreground = _t.Suave; flecha.Margin = new Thickness(8, 0, 0, 0); Grid.SetColumn(flecha, 2); Grid.SetRowSpan(flecha, 2);
            g.Children.Add(l0); g.Children.Add(v0); g.Children.Add(l1); g.Children.Add(v1); g.Children.Add(flecha);
            _provBtn.Content = g;
            _provBtn.ToolTip = "Clic para cambiar de IA, de modelo, de especialidad o la clave";
        }

        private void ConstruirAvisoVivo()
        {
            var pila = new StackPanel();
            pila.Children.Add(new TextBlock { Text = "Modo en vivo", FontWeight = FontWeights.SemiBold, Foreground = _t.Texto });
            pila.Children.Add(new TextBlock
            {
                Text = "Tu agente (Claude Code, Codex, OpenCode…) trabaja en su propio programa, con su suscripción. Este chat no se usa con él: " +
                       "aquí solo ves lo que hace y lo que te responde. Pídele las cosas en su programa.",
                Foreground = _t.Suave, FontSize = 11.5, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 6),
            });
            _notaBtn.Content = "Dejarle una nota"; _notaBtn.HorizontalAlignment = HorizontalAlignment.Left;
            _notaBtn.ToolTip = "Una nota que tu agente lee en su siguiente acción (si está quieto, no se entera hasta que lo llames)";
            _notaBtn.Click += (s, e) => { _notaAbierta = !_notaAbierta; ActualizarModoEntrada(); };
            pila.Children.Add(_notaBtn);
            _vivoAviso = new Border
            {
                Background = _t.Tarjeta, BorderBrush = _t.Borde, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6),
                Padding = new Thickness(8), Margin = new Thickness(6, 6, 6, 0), Child = pila, Visibility = Visibility.Collapsed,
            };
        }

        // Con un agente por suscripción el chat se bloquea (el agente corre en su programa): solo queda la nota opcional.
        private void ActualizarModoEntrada()
        {
            bool vivo = _prov != null && _prov.Vivo;
            _seccionApi.Visibility = vivo ? Visibility.Collapsed : Visibility.Visible;
            _vivoAviso.Visibility = vivo ? Visibility.Visible : Visibility.Collapsed;
            _entradaFila.Visibility = (!vivo || _notaAbierta) ? Visibility.Visible : Visibility.Collapsed;
            _notaBtn.Content = _notaAbierta ? "Ocultar la nota" : "Dejarle una nota";
            _adjSel.IsEnabled = !vivo;
        }

        internal void AbrirAjustes()
        {
            RefrescarProveedores();
            RefrescarPerfiles();
            _listaModelos.Children.Clear();
            _ajustes.Visibility = Visibility.Visible;
        }

        private void ConstruirAjustes()
        {
            _ajustes.Visibility = Visibility.Collapsed;
            _ajustes.Background = _t.Fondo;
            var sv = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
            var p = new StackPanel { Margin = new Thickness(10, 8, 10, 12) };

            var titulo = new Grid();
            titulo.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            titulo.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            titulo.Children.Add(new TextBlock { Text = "Configuración", FontWeight = FontWeights.SemiBold, FontSize = 15, Foreground = _t.Texto, VerticalAlignment = VerticalAlignment.Center });
            var cerrar = new Button { Content = Icono("\uE711", 12), Width = 30, ToolTip = "Cerrar" };
            cerrar.Click += (s, e) => _ajustes.Visibility = Visibility.Collapsed;
            Grid.SetColumn(cerrar, 1); titulo.Children.Add(cerrar);
            p.Children.Add(titulo);

            // licencia: solo si esta copia la exige (un paquete vendido). En el repo de desarrollo no aparece.
            _licSeccion.Children.Add(Etiqueta("Licencia"));
            _licEstado.Foreground = _t.Suave; _licEstado.TextWrapping = TextWrapping.Wrap; _licEstado.Margin = new Thickness(0, 0, 0, 4);
            _licSeccion.Children.Add(_licEstado);
            EstilizarTexto(_licClave); _licClave.ToolTip = "La clave que recibiste al comprar (AIA-XXXXX-XXXXX-XXXXX-XXXXX)";
            _licSeccion.Children.Add(_licClave);
            var licBotones = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
            var activar = new Button { Content = "Activar", Background = _t.Acento, Foreground = _t.AcentoTexto, BorderBrush = _t.Acento };
            activar.Click += async (s, e) => await LicenciaAsync("/api/licencia/activar", new { clave = _licClave.Text.Trim() }).ConfigureAwait(true);
            var prueba = new Button { Content = "Prueba gratis de 7 días", Margin = new Thickness(6, 0, 0, 0) };
            prueba.Click += async (s, e) => await LicenciaAsync("/api/licencia/prueba", new { }).ConfigureAwait(true);
            licBotones.Children.Add(activar); licBotones.Children.Add(prueba);
            _licSeccion.Children.Add(licBotones);
            p.Children.Add(_licSeccion);

            p.Children.Add(Etiqueta("Con qué IA quieres trabajar"));
            p.Children.Add(_listaProv);
            p.Children.Add(new TextBlock
            {
                Text = "Con una IA de API (Groq, Anthropic, OpenRouter…) el chat de este panel es el agente. Con «En vivo» (Claude Code, Codex, OpenCode…) " +
                       "el agente trabaja en su propio programa y aquí solo ves sus resultados.",
                Foreground = _t.Suave, FontSize = 11, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 4, 0, 0),
            });

            // lo que solo aplica a una IA de API
            _seccionApi.Children.Add(Etiqueta("Modelo"));
            EstilizarTexto(_modelo);
            _modelo.ToolTip = "Se puede escribir cualquier modelo del proveedor";
            _modelo.LostFocus += async (s, e) => await GuardarModeloAsync().ConfigureAwait(true);
            _seccionApi.Children.Add(_modelo);
            _modeloBtn.Content = "Ver los modelos disponibles"; _modeloBtn.Margin = new Thickness(0, 6, 0, 0); _modeloBtn.HorizontalAlignment = HorizontalAlignment.Left;
            _modeloBtn.Click += async (s, e) => await ListarModelosAsync().ConfigureAwait(true);
            _seccionApi.Children.Add(_modeloBtn);
            _seccionApi.Children.Add(_listaModelos);

            _seccionApi.Children.Add(Etiqueta("Clave de API"));
            _claveEstado.Foreground = _t.Suave; _claveEstado.Margin = new Thickness(0, 0, 0, 4); _claveEstado.TextWrapping = TextWrapping.Wrap;
            _seccionApi.Children.Add(_claveEstado);
            _clave.Background = _t.Tarjeta; _clave.Foreground = _t.Texto; _clave.BorderBrush = _t.Borde; _clave.Padding = new Thickness(4, 4, 4, 4);
            _seccionApi.Children.Add(_clave);
            var botones = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
            var guardar = new Button { Content = "Guardar", Background = _t.Acento, Foreground = _t.AcentoTexto };
            guardar.Click += async (s, e) => await GuardarClaveAsync(false).ConfigureAwait(true);
            var borrar = new Button { Content = "Borrar", Margin = new Thickness(6, 0, 0, 0) };
            borrar.Click += async (s, e) => await GuardarClaveAsync(true).ConfigureAwait(true);
            botones.Children.Add(guardar); botones.Children.Add(borrar);
            _seccionApi.Children.Add(botones);

            _seccionApi.Children.Add(Etiqueta("Especialidad (qué herramientas ve el modelo)"));
            _seccionApi.Children.Add(_listaPerfiles);
            _seccionApi.Children.Add(_perfilTools);

            _reglas.Content = "Reglas de dibujo del proyecto (gasta más tokens)"; _reglas.IsChecked = true; _reglas.Foreground = _t.Texto;
            _reglas.Margin = new Thickness(0, 10, 0, 0);
            _seccionApi.Children.Add(_reglas);

            _seccionApi.Children.Add(Etiqueta("Permisos al modificar el dibujo"));
            _seccionApi.Children.Add(_listaPermisos);
            _seccionApi.Children.Add(Etiqueta("Tope de gasto por pedido (US$)"));
            EstilizarTexto(_tope); _tope.Width = 90; _tope.HorizontalAlignment = HorizontalAlignment.Left; _tope.Text = "0";
            _tope.ToolTip = "0 = sin tope. Si un pedido pasa de esta cantidad, el agente se detiene al terminar la vuelta en curso.";
            _tope.LostFocus += async (s, e) => await GuardarTopeAsync().ConfigureAwait(true);
            _seccionApi.Children.Add(_tope);
            _seccionApi.Children.Add(new TextBlock { Text = "0 = sin tope. Lo dibujado se queda; el agente solo deja de seguir.", Foreground = _t.Suave, FontSize = 11, Margin = new Thickness(0, 3, 0, 0), TextWrapping = TextWrapping.Wrap });
            RefrescarPermisos();

            _seccionApi.Children.Add(Etiqueta("Temperatura"));
            _temp.Minimum = 0; _temp.Maximum = 1; _temp.Value = 0.2; _temp.TickFrequency = 0.1; _temp.IsSnapToTickEnabled = true;
            _seccionApi.Children.Add(_temp);
            p.Children.Add(_seccionApi);

            var web = new Button { Content = "Abrir todas las opciones en el navegador", Margin = new Thickness(0, 14, 0, 0) };
            web.Click += (s, e) => { if (_cli != null) try { Process.Start(new ProcessStartInfo(_cli.Base + "/") { UseShellExecute = true }); } catch { } };
            p.Children.Add(web);
            var listo = new Button { Content = "Listo", Margin = new Thickness(0, 8, 0, 0), Background = _t.Acento, Foreground = _t.AcentoTexto, Padding = new Thickness(8, 6, 8, 6) };
            listo.Click += (s, e) => _ajustes.Visibility = Visibility.Collapsed;
            p.Children.Add(listo);
            sv.Content = p;
            _ajustes.Children.Add(sv);
        }

        private void RefrescarPermisos()
        {
            _listaPermisos.Children.Clear();
            var opciones = new[]
            {
                ("destructivo", "Preguntar lo destructivo", "Borrar, purgar, cerrar, deshacer y comandos libres piden permiso. Dibujar no."),
                ("todo", "Preguntar todo lo que modifica", "Cada herramienta que toca el dibujo pide permiso. Lo más seguro, y lo más lento."),
                ("nada", "No preguntar nada", "El agente hace todo sin preguntar, incluso borrar. «Deshacer este pedido» sigue disponible."),
            };
            foreach (var (id, titulo, detalle) in opciones)
            {
                var ident = id;
                _listaPermisos.Children.Add(Fila(titulo, detalle, _modoPermisos == ident, async () =>
                {
                    _modoPermisos = ident; RefrescarPermisos();
                    if (_cli != null) try { using (await _cli.PostAsync("/api/preferencias", new { preferencias = new { modoPermisos = ident } }).ConfigureAwait(true)) { } } catch { }
                }));
            }
        }

        private async Task GuardarTopeAsync()
        {
            if (!double.TryParse(_tope.Text.Replace(',', '.'), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v) || v < 0) { v = 0; _tope.Text = "0"; }
            if (_cli != null) try { using (await _cli.PostAsync("/api/preferencias", new { preferencias = new { topeUSD = v } }).ConfigureAwait(true)) { } } catch { }
        }

        private double TopeActual() =>
            double.TryParse((_tope.Text ?? "").Replace(',', '.'), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var v) && v > 0 ? v : 0;

        private void MostrarLicencia(JsonElement lic)
        {
            _licObligatoria = lic.TryGetProperty("obligatoria", out var o) && o.ValueKind == JsonValueKind.True;
            _licValida = !_licObligatoria || (lic.TryGetProperty("valida", out var v) && v.ValueKind == JsonValueKind.True);
            _licSeccion.Visibility = _licObligatoria ? Visibility.Visible : Visibility.Collapsed;
            _licEstado.Text = lic.TryGetProperty("mensaje", out var m) && m.ValueKind == JsonValueKind.String ? m.GetString() : "";
            _licEstado.Foreground = _licValida ? _t.Ok : _t.Mal;
        }

        private async Task LicenciaAsync(string ruta, object cuerpo)
        {
            if (_cli == null) return;
            try
            {
                using (var doc = await _cli.PostAsync(ruta, cuerpo).ConfigureAwait(true))
                    if (doc.RootElement.TryGetProperty("licencia", out var lic))
                    {
                        // la respuesta trae el estado de la licencia; el mensaje listo lo da /api/estado
                        using (var est = await _cli.GetAsync("/api/estado").ConfigureAwait(true))
                            if (est.RootElement.TryGetProperty("licencia", out var l2)) MostrarLicencia(l2); else MostrarLicencia(lic);
                    }
            }
            catch (Exception ex) { _licEstado.Text = ex.Message; _licEstado.Foreground = _t.Mal; }
        }

        // Una fila elegible, a lo ancho y con el nombre completo (sin menús emergentes).
        private Button Fila(string titulo, string detalle, bool elegida, Action alElegir)
        {
            var pila = new StackPanel();
            pila.Children.Add(new TextBlock { Text = titulo, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap });
            if (!string.IsNullOrEmpty(detalle))
                pila.Children.Add(new TextBlock { Text = detalle, Foreground = _t.Suave, FontSize = 11, TextWrapping = TextWrapping.Wrap });
            var b = new Button
            {
                Content = pila, HorizontalContentAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 0, 0, 4), Padding = new Thickness(8, 6, 8, 6),
                BorderBrush = elegida ? _t.Acento : _t.Borde, BorderThickness = new Thickness(elegida ? 2 : 1),
            };
            b.Click += (s, e) => alElegir();
            return b;
        }

        private void RefrescarProveedores()
        {
            _listaProv.Children.Clear();
            foreach (var p in _provs)
            {
                var item = p;
                string detalle = item.Vivo ? "Claude Code, Codex, OpenCode…: trabajan en su programa; aquí ves lo que hacen"
                               : item.Puente ? "usa tu sesión"
                               : item.Clave ? "con clave guardada" : "falta la clave";
                _listaProv.Children.Add(Fila(item.Nombre.Replace(" · sin clave", ""), detalle, _prov != null && _prov.Id == item.Id,
                    async () => await ElegirProveedorAsync(item, true).ConfigureAwait(true)));
            }
        }

        private readonly Dictionary<string, string> _toolsPerfil = new Dictionary<string, string>();
        private readonly TextBlock _perfilTools = new TextBlock { TextWrapping = TextWrapping.Wrap, FontFamily = new FontFamily("Consolas"), FontSize = 11, Margin = new Thickness(0, 6, 0, 0) };

        // Los nombres de las herramientas de la especialidad elegida: lo que el agente puede (y no puede) hacer.
        private async Task MostrarToolsPerfilAsync()
        {
            _perfilTools.Foreground = _t.Suave;
            if (_cli == null) return;
            if (_toolsPerfil.TryGetValue(_perfil, out var ya)) { _perfilTools.Text = ya; return; }
            _perfilTools.Text = "Leyendo las herramientas de esta especialidad…";
            try
            {
                using (var doc = await _cli.GetAsync("/api/perfil_tools?perfil=" + Uri.EscapeDataString(_perfil)).ConfigureAwait(true))
                {
                    var nombres = doc.RootElement.GetProperty("tools").EnumerateArray().Select(x => x.GetString()).ToList();
                    var txt = "Herramientas de «" + _perfil + "» (" + nombres.Count + "):" + (char)10 + string.Join(" · ", nombres);
                    _toolsPerfil[_perfil] = txt;
                    _perfilTools.Text = txt;
                }
            }
            catch { _perfilTools.Text = "(no se pudo leer la lista de herramientas)"; }
        }

        private void RefrescarPerfiles()
        {
            _listaPerfiles.Children.Clear();
            foreach (var pf in _perfiles)
            {
                var item = pf;
                _listaPerfiles.Children.Add(Fila(item.id, item.tools + " herramientas" + (item.id == "todo" ? " (las ~300 a la vez: gasta ~100 mil tokens por mensaje y Groq/OpenAI aceptan máximo 128)" : item.id == "descubrir" ? " (las ~300, bajo demanda: el agente busca y usa las que necesita; la que conviene con una IA de API)" : item.id == "basico" ? " (dibujo simple)" : ""), item.id == _perfil, async () =>
                {
                    _perfil = item.id; RefrescarPerfiles(); ActualizarChip();
                    try { using (await _cli.PostAsync("/api/preferencias", new { preferencias = new { perfil = _perfil } }).ConfigureAwait(true)) { } } catch { }
                }));
            }
            _ = MostrarToolsPerfilAsync();
        }

        private async Task ListarModelosAsync()
        {
            if (_prov == null || _prov.Vivo || _cli == null) return;
            _listaModelos.Children.Clear();
            _listaModelos.Children.Add(new TextBlock { Text = "Pidiendo la lista de modelos…", Foreground = _t.Suave, Margin = new Thickness(0, 6, 0, 0) });
            try
            {
                using (var doc = await _cli.PostAsync("/api/modelos", new { proveedor = _prov.Id }).ConfigureAwait(true))
                {
                    _listaModelos.Children.Clear();
                    foreach (var m in doc.RootElement.GetProperty("modelos").EnumerateArray().Take(80))
                    {
                        var nombre = m.GetProperty("modelo").GetString();
                        var estado = m.TryGetProperty("estado", out var e) && e.ValueKind == JsonValueKind.String ? e.GetString() : "";
                        var b = Fila(nombre, estado == "?" ? "" : estado, nombre == _modelo.Text.Trim(), async () =>
                        {
                            _modelo.Text = nombre; await GuardarModeloAsync().ConfigureAwait(true);
                            await ListarModelosAsync().ConfigureAwait(true);
                        });
                        b.Margin = new Thickness(0, 4, 0, 0);
                        _listaModelos.Children.Add(b);
                    }
                }
            }
            catch (Exception ex)
            {
                _listaModelos.Children.Clear();
                _listaModelos.Children.Add(new TextBlock { Text = ex.Message, Foreground = _t.Mal, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 0) });
            }
        }

        private TextBlock Etiqueta(string texto) =>
            new TextBlock { Text = texto, Foreground = _t.Suave, FontSize = 11, Margin = new Thickness(0, 12, 0, 3) };

        // ------------------------------------------------------------------------------------------ arranque y estado

        public async Task IniciarAsync()
        {
            _estado.Text = "Arrancando el servidor del chat…";
            var (url, problema) = await _asegurar().ConfigureAwait(true);
            if (url == null)
            {
                _estado.Text = "";
                AgregarAviso(problema ?? "No pude arrancar el servidor del chat.");
                return;
            }
            _cli = new ChatCliente(url);
            _agente = new AgenteNativo(() => _cli);
            try
            {
                await CargarEstadoAsync().ConfigureAwait(true);
                await RestaurarAsync().ConfigureAwait(true);
                _estado.Text = "";
            }
            catch (Exception ex)
            {
                _estado.Text = "";
                AgregarAviso("No pude hablar con el servidor del chat: " + ex.Message);
            }
        }

        private async Task CargarEstadoAsync()
        {
            using (var doc = await _cli.GetAsync("/api/estado").ConfigureAwait(true))
            {
                var r = doc.RootElement;
                _provs.Clear(); _perfiles.Clear(); _modelos.Clear();
                foreach (var p in r.GetProperty("proveedores").EnumerateArray())
                {
                    string S(string k) => p.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : "";
                    bool B(string k) => p.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.True;
                    // La clave llega enmascarada («gsk_…ZxX4») o null: lo que importa es si existe.
                    bool tieneClave = p.TryGetProperty("clave", out var c) && c.ValueKind == JsonValueKind.String && c.GetString().Length > 0;
                    _provs.Add(new ProveedorItem { Id = S("id"), ModeloSugerido = S("modeloSugerido"), Detalle = S("detalle"), Clave = tieneClave, Puente = B("puente"), Vivo = B("vivo") });
                }
                if (r.TryGetProperty("perfiles", out var perfs))
                    foreach (var pf in perfs.EnumerateArray())
                        _perfiles.Add((pf.GetProperty("id").GetString(), pf.TryGetProperty("tools", out var n) ? n.GetInt32() : 0));
                string prefProv = null;
                if (r.TryGetProperty("preferencias", out var pr) && pr.ValueKind == JsonValueKind.Object)
                {
                    if (pr.TryGetProperty("proveedor", out var pp) && pp.ValueKind == JsonValueKind.String) prefProv = pp.GetString();
                    if (pr.TryGetProperty("perfil", out var pe) && pe.ValueKind == JsonValueKind.String) _perfil = pe.GetString();
                    if (pr.TryGetProperty("conReglas", out var cr)) _reglas.IsChecked = cr.ValueKind != JsonValueKind.False;
                    if (pr.TryGetProperty("temperatura", out var tm) && tm.ValueKind == JsonValueKind.Number) _temp.Value = tm.GetDouble();
                    if (pr.TryGetProperty("modoPermisos", out var mp) && mp.ValueKind == JsonValueKind.String) _modoPermisos = mp.GetString();
                    if (pr.TryGetProperty("topeUSD", out var tu) && tu.ValueKind == JsonValueKind.Number) _tope.Text = tu.GetDouble().ToString(System.Globalization.CultureInfo.InvariantCulture);
                    if (pr.TryGetProperty("modelos", out var ms) && ms.ValueKind == JsonValueKind.Object)
                        foreach (var m in ms.EnumerateObject())
                            if (m.Value.ValueKind == JsonValueKind.String) _modelos[m.Name] = m.Value.GetString();
                }
                var elegido = _provs.FirstOrDefault(x => x.Id == prefProv) ?? _provs.FirstOrDefault(x => x.Clave && !x.Vivo) ?? _provs.FirstOrDefault();
                RefrescarPerfiles(); RefrescarPermisos();
                if (r.TryGetProperty("licencia", out var licEstado) && licEstado.ValueKind == JsonValueKind.Object) MostrarLicencia(licEstado);
                if (elegido != null) await ElegirProveedorAsync(elegido, false).ConfigureAwait(true);
            }
        }

        private async Task ElegirProveedorAsync(ProveedorItem p, bool guardar)
        {
            _prov = p;
            _modelo.Text = _modelos.TryGetValue(p.Id, out var m) && m.Length > 0 ? m : p.ModeloSugerido;
            _modelo.IsEnabled = !p.Vivo;
            _modeloBtn.IsEnabled = !p.Vivo;
            _claveEstado.Text = p.Vivo ? p.Detalle : (p.Clave ? "Hay una clave guardada para " + p.Id + "." : "Todavía no hay clave para " + p.Id + ".");
            _placeholder.Text = p.Vivo ? "Mensaje para tu agente…" : "Escribe tu instrucción…";
            bool vivo = p.Vivo;
            _scroll.Visibility = vivo ? Visibility.Collapsed : Visibility.Visible;
            var vivoGrid = (UIElement)_vivoScroll.Parent;
            vivoGrid.Visibility = vivo ? Visibility.Visible : Visibility.Collapsed;
            if (vivo) VivoIniciar(); else VivoDetener();
            ActualizarChip(); RefrescarProveedores(); ActualizarModoEntrada();
            if (guardar)
            {
                try { using (await _cli.PostAsync("/api/preferencias", new { preferencias = new { proveedor = p.Id } }).ConfigureAwait(true)) { } }
                catch { /* la preferencia es una comodidad */ }
            }
        }

        private async Task GuardarModeloAsync()
        {
            if (_prov == null || _prov.Vivo || _cli == null) return;
            var m = _modelo.Text.Trim();
            if (m == (_modelos.TryGetValue(_prov.Id, out var antes) ? antes : "")) return;
            _modelos[_prov.Id] = m;
            ActualizarChip();
            try { using (await _cli.PostAsync("/api/preferencias", new { preferencias = new { modelos = _modelos } }).ConfigureAwait(true)) { } }
            catch { }
        }

        private async Task GuardarClaveAsync(bool borrar)
        {
            if (_prov == null || _prov.Vivo || _cli == null) return;
            try
            {
                if (borrar)
                    using (await _cli.PostAsync("/api/clave", new { proveedor = _prov.Id, borrar = true }).ConfigureAwait(true)) { }
                else
                {
                    if (_clave.Password.Trim().Length == 0) return;
                    using (await _cli.PostAsync("/api/clave", new { proveedor = _prov.Id, clave = _clave.Password.Trim() }).ConfigureAwait(true)) { }
                }
                _clave.Password = "";
                var id = _prov.Id;
                await CargarEstadoAsync().ConfigureAwait(true);
                var otra = _provs.FirstOrDefault(x => x.Id == id);
                if (otra != null) await ElegirProveedorAsync(otra, false).ConfigureAwait(true);
                _claveEstado.Text = borrar ? "Clave borrada." : "Clave guardada (cifrada en tu usuario de Windows).";
            }
            catch (Exception ex) { _claveEstado.Text = ex.Message; }
        }

        // ------------------------------------------------------------------------------------------ conversación

        private void MostrarSugerencias()
        {
            _lista.Children.Clear();
            _hayConversacion = false;
            _lista.Children.Add(Rotulo("NUEVA CONSULTA", _t.Acento));
            _lista.Children.Add(new TextBlock { Text = "¿Qué hacemos con este dibujo?", FontSize = 16, FontWeight = FontWeights.SemiBold, Foreground = _t.Texto, Margin = new Thickness(0, 2, 0, 4), TextWrapping = TextWrapping.Wrap });
            _lista.Children.Add(new TextBlock { Text = "Consulto, dibujo, reviso y cuantifico. Veo el dibujo abierto y tu selección.", Foreground = _t.Suave, Margin = new Thickness(0, 0, 0, 14), TextWrapping = TextWrapping.Wrap });
            int n = 0;
            foreach (var s in new[] { "¿Qué hay en el dibujo abierto?", "Lista las capas del dibujo", "Revisa el plano con check_all" })
            {
                var texto = s; n++;
                var fila = new StackPanel { Orientation = Orientation.Horizontal };
                fila.Children.Add(new TextBlock { Text = n.ToString("00"), FontFamily = Mono, FontSize = 10.5, Foreground = _t.Acento, Width = 26, VerticalAlignment = VerticalAlignment.Center });
                fila.Children.Add(new TextBlock { Text = texto, Foreground = _t.Texto, TextWrapping = TextWrapping.Wrap });
                var b = new Button { Content = fila, HorizontalContentAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 0, 0, 2), Padding = new Thickness(6, 8, 6, 8), Style = _estiloFantasma };
                b.Click += async (x, y) => { _entrada.Text = texto; await EnviarAsync().ConfigureAwait(true); };
                _lista.Children.Add(b);
            }
        }

        private void QuitarSugerencias()
        {
            if (_hayConversacion) return;
            _lista.Children.Clear();
            _hayConversacion = true;
        }

        private async Task RestaurarAsync()
        {
            await Task.Yield();
            var eventos = _agente.Eventos;
            if (eventos.Count == 0) return;
            QuitarSugerencias();
            foreach (var nodo in eventos.Skip(Math.Max(0, eventos.Count - 120)))
            {
                using (var doc = JsonDocument.Parse(nodo.ToJsonString()))
                {
                    var ev = doc.RootElement;
                    var tipo = Texto(ev, "tipo");
                    if (tipo == "usuario") AgregarUsuario(Texto(ev, "texto"));
                    else Procesar(ev);
                }
            }
            AgregarNota("Conversación anterior restaurada. «＋» la borra.", false);
        }

        private static string Texto(JsonElement e, string clave) =>
            e.ValueKind == JsonValueKind.Object && e.TryGetProperty(clave, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : "";

        private bool AlFinal() => _scroll.VerticalOffset + _scroll.ViewportHeight >= _scroll.ExtentHeight - 40;

        private void Agregar(UIElement el)
        {
            bool final = AlFinal();
            _lista.Children.Add(el);
            if (final) Dispatcher.BeginInvoke(new Action(() => _scroll.ScrollToEnd()), DispatcherPriority.Background);
        }

        /// <summary>Un rótulo como la línea de cota de un plano:  ─ TÍTULO ───────────┤</summary>
        private UIElement Rotulo(string texto, Brush color)
        {
            var g = new Grid { Margin = new Thickness(0, 12, 0, 5) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var ini = new Border { Width = 12, Height = 1, Background = color, VerticalAlignment = VerticalAlignment.Center };
            var tb = new TextBlock { Text = Espaciado(texto), FontFamily = Mono, FontSize = 9.5, Foreground = color, Margin = new Thickness(7, 0, 7, 1), VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(tb, 1);
            var linea = new Border { Height = 1, Background = _t.Borde, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(linea, 2);
            var fin = new Border { Width = 1, Height = 7, Background = _t.Borde, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(fin, 3);
            g.Children.Add(ini); g.Children.Add(tb); g.Children.Add(linea); g.Children.Add(fin);
            return g;
        }

        // Solo lo usa la vista «En vivo»: un recuadro de filo fino.
        private Border Burbuja(UIElement contenido, Brush fondo, Brush borde, HorizontalAlignment lado)
        {
            return new Border
            {
                Background = Brushes.Transparent, BorderBrush = ReferenceEquals(borde, Brushes.Transparent) ? _t.Borde : borde, BorderThickness = new Thickness(1),
                Padding = new Thickness(8, 6, 8, 7), Margin = new Thickness(lado == HorizontalAlignment.Right ? 24 : 0, 4, lado == HorizontalAlignment.Left ? 10 : 0, 4), Child = contenido,
            };
        }

        private void AgregarUsuario(string texto, string adjunto = null)
        {
            // Lo que se restaura del historial trae el bloque «[Contexto de AutoCAD]...» pegado al mensaje: se separa
            // para no mostrar la lista de handles.
            if (adjunto == null && texto != null && texto.StartsWith("[Contexto de AutoCAD]", StringComparison.Ordinal))
            {
                var corte = texto.IndexOf("\n\n", StringComparison.Ordinal);
                if (corte > 0)
                {
                    var m = System.Text.RegularExpressions.Regex.Match(texto.Substring(0, corte), @"seleccionadas (\d+)");
                    adjunto = "📎 " + (m.Success ? m.Groups[1].Value : "varias") + " entidad(es) de AutoCAD";
                    texto = texto.Substring(corte + 2);
                }
            }
            _nPaso = 0; _primerAsistente = true;          // cada pedido empieza su propia numeración de pasos
            var pila = new StackPanel { Margin = new Thickness(0, 0, 0, 2) };
            pila.Children.Add(Rotulo("TÚ", _t.Suave));
            pila.Children.Add(new TextBlock { Text = texto, TextWrapping = TextWrapping.Wrap, Foreground = _t.Texto, FontSize = 13, LineHeight = 19, LineStackingStrategy = LineStackingStrategy.BlockLineHeight });
            if (adjunto != null)
                pila.Children.Add(new TextBlock { Text = adjunto, FontFamily = Mono, Foreground = _t.Suave, FontSize = 10, Margin = new Thickness(0, 4, 0, 0) });
            Agregar(pila);
        }

        private void AgregarAsistente(string texto)
        {
            var pila = new StackPanel { Margin = new Thickness(0, 0, 0, 4) };
            if (_primerAsistente) { pila.Children.Add(Rotulo("ASISTENTE", _t.Acento)); _primerAsistente = false; }
            else pila.Children.Add(new Border { Height = 6 });
            pila.Children.Add(ChatMarkdown.Render(texto, _t));
            var copiar = new MenuItem { Header = "Copiar" };
            copiar.Click += (s, e) => { try { Clipboard.SetText(texto); } catch { } };
            pila.ContextMenu = new ContextMenu { Items = { copiar } };
            Agregar(pila);
        }

        private void AgregarAviso(string texto)
        {
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(18) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.Children.Add(new TextBlock { Text = "!", FontFamily = Mono, FontWeight = FontWeights.Bold, Foreground = _t.Mal });
            var tb = new TextBlock { Text = texto, TextWrapping = TextWrapping.Wrap, Foreground = _t.Texto }; Grid.SetColumn(tb, 1); g.Children.Add(tb);
            Agregar(new Border { BorderBrush = _t.Mal, BorderThickness = new Thickness(1), Padding = new Thickness(8, 6, 8, 7), Margin = new Thickness(0, 6, 0, 6), Child = g });
        }

        private void AgregarNota(string texto, bool franja = true)
        {
            Agregar(new TextBlock { Text = "▸ " + texto, Foreground = _t.Suave, FontSize = 10.5, Margin = new Thickness(0, 5, 0, 5), TextWrapping = TextWrapping.Wrap });
        }

        private string SiguientePaso() => (++_nPaso).ToString("00");

        // Un paso del agente, como una línea del índice de un plano:   01  Dibujar círculo ·········· ✓
        // Mientras corre, la guía de puntos «marcha» y un cursor parpadea; al terminar queda quieta y el filo cuenta cómo salió.
        internal sealed class TarjetaTool
        {
            public Border Raiz;
            public TextBlock Estado, Etiqueta, Detalle, Resumen, Extra;
            public System.Windows.Shapes.Line Guia;
            public string Nombre;
            public bool Abierta, Fallo;
            public string Completo = "", Corto = "";

            public static TarjetaTool Crear(ChatTema t, string nombre, string args, string numero = "")
            {
                var c = new TarjetaTool { Nombre = nombre };
                var g = new Grid();
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(26) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(22) });
                for (int i = 0; i < 4; i++) g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                var num = new TextBlock { Text = string.IsNullOrEmpty(numero) ? "·" : numero, FontFamily = Mono, FontSize = 10.5, Foreground = t.Suave, VerticalAlignment = VerticalAlignment.Center };
                c.Etiqueta = new TextBlock { Text = Frase(nombre), Foreground = t.Texto, FontSize = 12.5, TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center };
                Grid.SetColumn(c.Etiqueta, 1);
                c.Guia = new System.Windows.Shapes.Line
                {
                    X1 = 0, X2 = 1, Y1 = 0, Y2 = 0, Stretch = Stretch.Fill, Stroke = t.Acento, StrokeThickness = 1,
                    StrokeDashArray = new DoubleCollection { 1, 3 }, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 5, 8, 0),
                };
                Grid.SetColumn(c.Guia, 2);
                Marchar(c.Guia);
                c.Estado = new TextBlock { Text = "▍", FontFamily = Mono, FontSize = 13, Foreground = t.Acento, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
                Grid.SetColumn(c.Estado, 3);
                Parpadear(c.Estado);

                // el nombre técnico y los argumentos quedan plegados: se ven al hacer clic en el paso
                c.Detalle = new TextBlock { Text = nombre + (string.IsNullOrEmpty(args) ? "" : "  ·  " + args), FontFamily = Mono, FontSize = 10.5, Foreground = t.Suave, TextWrapping = TextWrapping.Wrap, Visibility = Visibility.Collapsed, Margin = new Thickness(26, 2, 0, 0) };
                Grid.SetColumn(c.Detalle, 0); Grid.SetColumnSpan(c.Detalle, 4); Grid.SetRow(c.Detalle, 1);
                c.Resumen = new TextBlock { FontFamily = Mono, FontSize = 10.5, Foreground = t.Mal, TextWrapping = TextWrapping.Wrap, Visibility = Visibility.Collapsed, Margin = new Thickness(26, 2, 0, 0), MaxHeight = 64 };
                Grid.SetColumn(c.Resumen, 0); Grid.SetColumnSpan(c.Resumen, 4); Grid.SetRow(c.Resumen, 2);
                c.Extra = new TextBlock { Background = t.Codigo, Padding = new Thickness(7), FontFamily = Mono, FontSize = 10.5, Foreground = t.Texto, TextWrapping = TextWrapping.Wrap, Visibility = Visibility.Collapsed, Margin = new Thickness(26, 3, 0, 2) };
                Grid.SetColumn(c.Extra, 0); Grid.SetColumnSpan(c.Extra, 4); Grid.SetRow(c.Extra, 3);

                g.Children.Add(num); g.Children.Add(c.Etiqueta); g.Children.Add(c.Guia); g.Children.Add(c.Estado);
                g.Children.Add(c.Detalle); g.Children.Add(c.Resumen); g.Children.Add(c.Extra);
                c.Raiz = new Border { Background = Brushes.Transparent, Padding = new Thickness(0, 4, 0, 4), Child = g, Cursor = Cursors.Hand };
                c.Raiz.MouseEnter += (s, e) => c.Raiz.Background = t.Tarjeta;
                c.Raiz.MouseLeave += (s, e) => c.Raiz.Background = Brushes.Transparent;
                c.Raiz.MouseLeftButtonUp += (s, e) => { c.Abierta = !c.Abierta; c.Pintar(); };
                return c;
            }

            private void Pintar()
            {
                bool hay = Completo.Length > 0;
                bool largo = Completo.Length > Corto.Length;
                // Si salió bien no se enseña nada más que el ✓; si falló, el motivo en corto. El detalle completo, al hacer clic.
                Resumen.Visibility = hay && !Abierta && Fallo ? Visibility.Visible : Visibility.Collapsed;
                Extra.Visibility = hay && Abierta ? Visibility.Visible : Visibility.Collapsed;
                Detalle.Visibility = Abierta ? Visibility.Visible : Visibility.Collapsed;
                Resumen.Text = Corto + (largo ? "   ▸ clic para ver todo" : "");
            }

            public void Resolver(ChatTema t, bool ok, string texto, string tiempo)
            {
                Fallo = !ok;
                Estado.BeginAnimation(UIElement.OpacityProperty, null);
                Estado.Opacity = 1; Estado.FontSize = 12; Estado.Text = ok ? "✓" : "✗"; Estado.Foreground = ok ? t.Ok : t.Mal;
                Guia.BeginAnimation(System.Windows.Shapes.Shape.StrokeDashOffsetProperty, null);
                Guia.Stroke = ok ? t.Borde : t.Mal;
                Etiqueta.Foreground = ok ? t.Suave : t.Mal;
                texto = texto ?? "";
                Completo = texto.Length > 3000 ? texto.Substring(0, 2997) + "…" : texto;
                var plano = System.Text.RegularExpressions.Regex.Replace(Completo, @"\s+", " ").Trim();
                Corto = plano.Length > 150 ? plano.Substring(0, 147) + "…" : plano;
                Extra.Text = Completo;
                if (!string.IsNullOrEmpty(tiempo)) Detalle.Text = (Detalle.Text.Length > 0 ? Detalle.Text + "  ·  " : "") + tiempo;
                Pintar();
            }
        }

        private static void Parpadear(UIElement el) =>
            el.BeginAnimation(UIElement.OpacityProperty, new System.Windows.Media.Animation.DoubleAnimation(1, 0.12, TimeSpan.FromMilliseconds(450))
            { AutoReverse = true, RepeatBehavior = System.Windows.Media.Animation.RepeatBehavior.Forever });

        private static void Marchar(System.Windows.Shapes.Shape s) =>
            s.BeginAnimation(System.Windows.Shapes.Shape.StrokeDashOffsetProperty, new System.Windows.Media.Animation.DoubleAnimation(0, -4, TimeSpan.FromMilliseconds(500))
            { RepeatBehavior = System.Windows.Media.Animation.RepeatBehavior.Forever });

        // ------------------------------------------------------------------------------------------ actividad y frases

        private void MostrarActividad(string fase)
        {
            if (!_trabajando) return;            // al restaurar la conversación no hay nada en curso
            _fase = fase;
            _actividadTxt.Text = _fase + new string('.', _puntos);
            _actividad.Visibility = Visibility.Visible;
            if (!_animTimer.IsEnabled)
            {
                _animTimer.Start();
                _trazo.BeginAnimation(ScaleTransform.ScaleXProperty, new System.Windows.Media.Animation.DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(1800))
                { EasingFunction = new System.Windows.Media.Animation.CubicEase { EasingMode = System.Windows.Media.Animation.EasingMode.EaseInOut }, RepeatBehavior = System.Windows.Media.Animation.RepeatBehavior.Forever });
            }
        }

        private void OcultarActividad()
        {
            _animTimer.Stop();
            _trazo.BeginAnimation(ScaleTransform.ScaleXProperty, null);
            _actividad.Visibility = Visibility.Collapsed;
        }

        internal static bool EsDescubrimiento(string nombre) => nombre == "buscar_herramientas" || nombre == "describir_herramienta";

        private static readonly Dictionary<string, string> Sustantivos = new Dictionary<string, string>
        {
            ["circle"] = "círculo", ["line"] = "línea", ["polyline"] = "polilínea", ["arc"] = "arco", ["text"] = "texto", ["mtext"] = "texto",
            ["hatch"] = "achurado", ["rectangle"] = "rectángulo", ["layer"] = "capa", ["block"] = "bloque", ["table"] = "tabla",
            ["viewport"] = "vista", ["layout"] = "distribución", ["leader"] = "directriz", ["entity"] = "entidad", ["entities"] = "entidades",
            ["stairs"] = "escalera", ["road"] = "calle", ["north"] = "norte", ["spline"] = "curva", ["ellipse"] = "elipse", ["polygon"] = "polígono",
            ["sheet"] = "lámina", ["walls"] = "muros", ["wall_network"] = "muros", ["dimension"] = "cota", ["legend"] = "leyenda",
        };

        /// <summary>Cómo se cuenta una herramienta a la persona: una frase, no el nombre técnico.</summary>
        internal static string Frase(string n)
        {
            n = n ?? "";
            switch (n)
            {
                case "buscar_herramientas": return "Buscando herramientas";
                case "describir_herramienta": return "Leyendo cómo se usa una herramienta";
                case "save_drawing": return "Guardando el dibujo";
                case "capture_viewport": return "Mirando el dibujo";
                case "zoom_extents": case "zoom_window": return "Ajustando la vista";
                case "suggest_layout": return "Diseñando la distribución";
                case "draw_layout": return "Dibujando la planta";
                case "place_furniture": case "suggest_furniture": return "Amueblando";
                case "label_rooms": case "place_labels": return "Rotulando";
                case "run_command": return "Ejecutando un comando de AutoCAD";
                case "set_layer": return "Configurando una capa";
                case "undo": return "Deshaciendo";
                case "export_pdf": return "Exportando a PDF";
                case "create_sheet": return "Preparando la lámina";
                case "create_wall_network": case "create_walls": return "Levantando muros";
                case "check_all": return "Revisando el plano";
                case "calculate_quantities": return "Calculando cantidades";
            }
            string Resto(string prefijo)
            {
                var r = n.Substring(prefijo.Length);
                if (Sustantivos.TryGetValue(r, out var s)) return s;
                if (r.StartsWith("dimension")) return "cota";
                return r.Replace('_', ' ');
            }
            if (n.StartsWith("create_")) return "Dibujando " + Resto("create_");
            if (n.StartsWith("delete_")) return "Borrando " + Resto("delete_");
            if (n.StartsWith("dimension_")) return "Acotando";
            if (n.StartsWith("list_") || n.StartsWith("get_") || n.StartsWith("query_") || n.StartsWith("check_") || n.StartsWith("describe_")
                || n.StartsWith("aggregate_") || n.StartsWith("measure_")) return "Revisando el dibujo";
            if (n.StartsWith("move_") || n.StartsWith("rotate_") || n.StartsWith("scale_") || n.StartsWith("mirror_") || n.StartsWith("copy_")
                || n.StartsWith("offset_") || n.StartsWith("array_")) return "Modificando el dibujo";
            if (n.StartsWith("export_")) return "Exportando";
            if (n.StartsWith("design_") || n.StartsWith("suggest_") || n.StartsWith("calculate_")) return "Calculando";
            return "Ejecutando " + n.Replace('_', ' ');
        }

        // Una acción destructiva pide permiso con un recuadro (no con un diálogo: los emergentes no abren dentro de una paleta).
        private void MostrarPermiso(JsonElement ev)
        {
            var id = Texto(ev, "id");
            var nombre = Texto(ev, "nombre");
            var detalle = ev.TryGetProperty("args", out var a) ? ResumenArgs(a) : "";
            var pila = new StackPanel();
            pila.Children.Add(Rotulo("CONFIRMAR", _t.Aviso));
            pila.Children.Add(new TextBlock { Text = nombre, FontFamily = Mono, FontWeight = FontWeights.SemiBold, Foreground = _t.Texto, TextWrapping = TextWrapping.Wrap });
            if (detalle.Length > 0)
                pila.Children.Add(new TextBlock { Text = detalle, FontFamily = Mono, FontSize = 10.5, Foreground = _t.Suave, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 0) });
            var riesgo = Texto(ev, "resumen");
            if (riesgo.Length > 0)
                pila.Children.Add(new TextBlock { Text = riesgo, FontFamily = Mono, FontSize = 11, FontWeight = FontWeights.SemiBold, Foreground = riesgo.Contains("TODO") || riesgo.Contains("muchas") ? _t.Mal : _t.Aviso, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 4, 0, 0) });
            var respuesta = new TextBlock { Foreground = _t.Texto, FontFamily = Mono, FontSize = 11, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 6, 0, 0), TextWrapping = TextWrapping.Wrap };
            var botones = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            Button B(string texto, int decision)
            {
                var b = new Button { Content = texto, FontFamily = Mono, FontSize = 10.5, Margin = new Thickness(0, 0, 6, 4), Padding = new Thickness(10, 4, 10, 4) };
                if (decision == 1) { b.Background = _t.Aviso; b.BorderBrush = _t.Aviso; b.Foreground = _t.AcentoTexto; b.FontWeight = FontWeights.Bold; }
                b.Click += (s, e) =>
                {
                    botones.Visibility = Visibility.Collapsed;
                    respuesta.Text = decision == 0 ? "✗ RECHAZADO" : decision == 2 ? "✓ PERMITIDO · sin volver a preguntar por esta herramienta en esta conversación" : "✓ PERMITIDO";
                    respuesta.Foreground = decision == 0 ? _t.Mal : _t.Ok;
                    respuesta.Visibility = Visibility.Visible;
                    _agente?.ResolverPermiso(id, decision);
                };
                return b;
            }
            botones.Children.Add(B("PERMITIR", 1));
            botones.Children.Add(B("RECHAZAR", 0));
            botones.Children.Add(B("PERMITIR SIEMPRE ESTA", 2));
            pila.Children.Add(botones);
            pila.Children.Add(respuesta);
            Agregar(new Border { BorderBrush = _t.Aviso, BorderThickness = new Thickness(1), Padding = new Thickness(10, 0, 10, 6), Margin = new Thickness(0, 8, 0, 6), Child = pila });
        }

        // «Deshacer este pedido»: vuelve a la marca de UNDO que se puso antes de que el pedido tocara el dibujo.
        private readonly List<Button> _botonesDeshacer = new List<Button>();

        private void MostrarDeshacer()
        {
            var pila = new StackPanel { Margin = new Thickness(0, 8, 0, 8) };
            var b = new Button { Content = "↶  DESHACER ESTE PEDIDO", FontFamily = Mono, FontSize = 10.5, HorizontalAlignment = HorizontalAlignment.Left, Padding = new Thickness(10, 4, 10, 4), Style = _estiloCajetin };
            _botonesDeshacer.Add(b);
            b.Click += async (s, e) =>
            {
                b.IsEnabled = false;
                if (_agente == null) return;
                var (ok, mensaje) = await _agente.DeshacerAsync().ConfigureAwait(true);
                if (ok) AgregarNota("↶ " + mensaje); else { AgregarAviso(mensaje); b.IsEnabled = true; }
            };
            pila.Children.Add(b);
            pila.Children.Add(new TextBlock { Text = "Revierte todo lo que hizo este pedido (también lo que edites a mano después).", Foreground = _t.Suave, FontSize = 10, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 3, 0, 0) });
            Agregar(pila);
        }

        private void DesactivarDeshacer()
        {
            foreach (var bt in _botonesDeshacer) bt.IsEnabled = false;
            _botonesDeshacer.Clear();
        }

        private static string ResumenArgs(JsonElement args)
        {
            if (args.ValueKind != JsonValueKind.Object) return "";
            // Algunos modelos abiertos mandan {"name": "tool", "arguments": {...}}: lo que importa son los argumentos.
            if (args.TryGetProperty("arguments", out var interno) && interno.ValueKind == JsonValueKind.Object) args = interno;
            var sb = new StringBuilder();
            foreach (var p in args.EnumerateObject())
            {
                // un modelo abierto a veces manda una clave vacía con un objeto vacío: no aporta nada
                if (string.IsNullOrWhiteSpace(p.Name) && (p.Value.ValueKind == JsonValueKind.Null || p.Value.GetRawText() == "{}")) continue;
                if (sb.Length > 0) sb.Append(", ");
                sb.Append(p.Name).Append('=').Append(p.Value.ValueKind == JsonValueKind.String ? p.Value.GetString() : p.Value.GetRawText());
                if (sb.Length > 110) break;
            }
            var s = sb.ToString();
            return s.Length > 110 ? s.Substring(0, 107) + "…" : s;
        }

        /// <summary>Un evento del flujo del servidor (el mismo que consume la interfaz web).</summary>
        private void Procesar(JsonElement ev)
        {
            switch (Texto(ev, "tipo"))
            {
                case "inicio":
                    {
                        // Solo el modelo, discreto: cuántas herramientas ve o cómo las descubre es cosa interna.
                        AgregarNota(Texto(ev, "modelo"), false);
                        _estado.Text = Texto(ev, "modelo");
                        break;
                    }
                case "texto":
                    AgregarAsistente(Texto(ev, "texto"));
                    break;
                case "tool":
                    {
                        var nombre = Texto(ev, "nombre");
                        MostrarActividad(Frase(nombre));
                        if (EsDescubrimiento(nombre)) break;          // buscar y leer herramientas: se ve como «Buscando herramientas…», sin tarjeta
                        var c = TarjetaTool.Crear(_t, nombre, ev.TryGetProperty("args", out var a) ? ResumenArgs(a) : "", SiguientePaso());
                        if (!_pendientes.TryGetValue(nombre, out var cola)) _pendientes[nombre] = cola = new Queue<TarjetaTool>();
                        cola.Enqueue(c);
                        Agregar(c.Raiz);
                        break;
                    }
                case "resultado":
                    {
                        var nombre = Texto(ev, "nombre");
                        MostrarActividad("Pensando");
                        if (EsDescubrimiento(nombre)) break;
                        bool error = ev.TryGetProperty("error", out var er) && er.ValueKind == JsonValueKind.True;
                        if (_pendientes.TryGetValue(nombre, out var cola) && cola.Count > 0)
                            cola.Dequeue().Resolver(_t, !error, Texto(ev, "texto"), null);
                        break;
                    }
                case "aviso":
                    AgregarAviso(Texto(ev, "texto"));
                    break;
                case "permiso":
                    MostrarActividad("Esperando tu permiso");
                    MostrarPermiso(ev);
                    break;
                case "deshacer":
                    MostrarDeshacer();
                    break;
                case "nota":
                    if (ev.TryGetProperty("tecnica", out var tecnica) && tecnica.ValueKind == JsonValueKind.True) break;     // avisos internos del agente
                    AgregarNota(Texto(ev, "texto"));
                    break;
                case "uso":
                    if (ev.TryGetProperty("total", out var tot) && tot.ValueKind == JsonValueKind.Number) _tokens = tot.GetInt32();
                    if (ev.TryGetProperty("vueltas", out var v) && v.ValueKind == JsonValueKind.Number) _vueltas = v.GetInt32();
                    if (ev.TryGetProperty("costoUSD", out var cu) && cu.ValueKind == JsonValueKind.Number) _costo = cu.GetDouble();
                    _estado.Text = _tokens.ToString("N0") + " tokens · " + _vueltas + " v." + (_costo > 0 ? " · US$" + _costo.ToString("0.0000") : "");
                    break;
            }
        }

        private async Task EnviarAsync()
        {
            if (_trabajando || _cli == null || _prov == null) return;
            var texto = _entrada.Text.Trim();
            if (texto.Length == 0) return;
            if (_prov.Vivo)
            {
                _entrada.Clear();
                try { using (await _cli.PostAsync("/api/vivo/mensaje", new { texto }).ConfigureAwait(true)) { } await VivoSondearAsync().ConfigureAwait(true); }
                catch (Exception ex) { _vivoEstado.Text = "No se pudo enviar: " + ex.Message; }
                return;
            }
            if (_licObligatoria && !_licValida)
            {
                _ajustes.Visibility = Visibility.Visible;
                return;          // la sección de licencia arriba dice qué hacer
            }
            if (!_prov.Clave && !_prov.Puente)
            {
                _ajustes.Visibility = Visibility.Visible;
                _claveEstado.Text = "Falta la clave de " + _prov.Id + ": pégala aquí abajo y pulsa Guardar.";
                return;
            }

            string contexto = null;
            int sel = 0;
            if (_adjSel.IsChecked == true && _ctx.Seleccionados > 0)
            {
                sel = _ctx.Seleccionados;
                contexto = _ctx.DescribirSeleccion(30);
            }
            DesactivarDeshacer();
            QuitarSugerencias();
            AgregarUsuario(texto, sel > 0 ? "📎 " + sel + " entidad(es) de AutoCAD" : null);
            _entrada.Clear();
            _adjSel.IsChecked = false;

            _trabajando = true;
            _enviar.Content = "DETENER";
            _estado.Text = "";
            MostrarActividad("Pensando");
            _cts = new CancellationTokenSource();
            try
            {
                var mensaje = contexto == null ? texto : contexto + "\n\n" + texto;
                if (_prov.Puente)
                {
                    // Un puente a un CLI (Claude Code) lo maneja el servidor Python: no hay bucle nuestro de por medio.
                    await _cli.ChatAsync(new
                    {
                        mensaje, imagenes = new string[0], proveedor = _prov.Id, modelo = _modelo.Text.Trim(), perfil = _perfil,
                        conReglas = _reglas.IsChecked == true, temperatura = _temp.Value, topeUSD = 0, contexto = "",
                    }, Procesar, _cts.Token).ConfigureAwait(true);
                }
                else
                {
                    await _agente.EjecutarAsync(new PedidoAgente
                    {
                        Mensaje = mensaje, Proveedor = _prov.Id, Modelo = _modelo.Text.Trim(), Perfil = _perfil,
                        ConReglas = _reglas.IsChecked == true, Temperatura = _temp.Value, ModoPermisos = _modoPermisos, TopeUSD = TopeActual(),
                    }, Procesar, _cts.Token).ConfigureAwait(true);
                }
            }
            catch (ChatError e) { AgregarAviso(e.Message); }
            catch (OperationCanceledException) { }
            catch (Exception e) when (!_cts.IsCancellationRequested)
            {
                AgregarAviso("Se cortó la conexión: " + e.Message);
                // El servidor pudo reiniciarse: se vuelve a levantar y a conectar solo, sin tener que abrir el panel de nuevo.
                try
                {
                    var (url, _) = await _asegurar().ConfigureAwait(true);
                    if (url != null) { _cli = new ChatCliente(url); AgregarAviso("Reconecté con el servidor del chat. Envía el mensaje otra vez."); }
                }
                catch (Exception) { }
            }
            finally
            {
                _trabajando = false;
                OcultarActividad();
                _enviar.Content = "ENVIAR";
                foreach (var cola in _pendientes.Values) cola.Clear();
                var t = _estado.Text;
                if (t.EndsWith(" · trabajando…", StringComparison.Ordinal)) _estado.Text = t.Substring(0, t.Length - " · trabajando…".Length);
                else if (t == "trabajando…") _estado.Text = "";
            }
        }

        private void Detener()
        {
            try { _cts?.Cancel(); } catch { }
            if (_cli != null && _prov != null && _prov.Puente) _ = _cli.PostAsync("/api/cancelar", new { }).ContinueWith(t => { var _ = t.Exception; });
            AgregarNota("Detenido. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir.");
        }

        private async Task NuevaAsync()
        {
            if (_trabajando || _cli == null) return;
            _agente?.Reiniciar();
            DesactivarDeshacer();
            try { using (await _cli.PostAsync("/api/reset", new { }).ConfigureAwait(true)) { } } catch { }      // la sesión de los puentes
            _pendientes.Clear();
            _tokens = _vueltas = 0; _costo = 0;
            _estado.Text = "";
            MostrarSugerencias();
        }

        // ------------------------------------------------------------------------------------------ AutoCAD

        private void ActualizarContexto()
        {
            var nombre = _ctx.NombreDibujo;
            int n = _ctx.Seleccionados;
            _ctxTexto.Inlines.Clear();
            _ctxTexto.Inlines.Add(new System.Windows.Documents.Run(Espaciado("DIBUJO") + "  ") { Foreground = _t.Suave, FontSize = 8.5 });
            _ctxTexto.Inlines.Add(new System.Windows.Documents.Run(string.IsNullOrEmpty(nombre) ? "(sin dibujo)" : nombre));
            if (n > 0) _ctxTexto.Inlines.Add(new System.Windows.Documents.Run("   ·   " + n + " sel.") { Foreground = _t.Acento });
            _adjSel.Visibility = n > 0 ? Visibility.Visible : Visibility.Collapsed;
            if (n == 0) _adjSel.IsChecked = false;
        }

        // ------------------------------------------------------------------------------------------ modo «en vivo»

        private void VivoIniciar()
        {
            if (_vivoTimer != null) return;
            _vivoTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1200) };
            _vivoTimer.Tick += async (s, e) => await VivoSondearAsync().ConfigureAwait(true);
            _vivoTimer.Start();
            _ = VivoSondearAsync();
            _ = VivoInfoAsync();
        }

        private void VivoDetener()
        {
            if (_vivoTimer == null) return;
            _vivoTimer.Stop();
            _vivoTimer = null;
        }

        private async Task VivoInfoAsync()
        {
            try
            {
                using (var doc = await _cli.GetAsync("/api/vivo/info").ConfigureAwait(true))
                    _vivoAyuda.Text = "Conecta tu agente una sola vez a este servidor de AutoCAD.\n\nClaude Code (terminal):\n" +
                                      Texto(doc.RootElement, "claude") + "\n\nOtro agente MCP: comando\n" + Texto(doc.RootElement, "python") +
                                      "\nargumento\n" + Texto(doc.RootElement, "servidor") +
                                      "\n\nDespués trabaja con él en su programa: aquí ves cada herramienta que use, y lo que escribas abajo le llega en su siguiente acción (si está quieto, escríbele en su programa).";
            }
            catch { }
        }

        private async Task VivoSondearAsync()
        {
            if (_vivoOcupado || _cli == null) return;
            _vivoOcupado = true;
            try
            {
                var limite = _vivoPrimera ? 40 : 0;
                using (var a = await _cli.GetAsync("/api/vivo/actividad?desde=" + _posAct + "&limite=" + limite).ConfigureAwait(true))
                using (var b = await _cli.GetAsync("/api/vivo/bandeja?desde=" + _posBan).ConfigureAwait(true))
                {
                    _posAct = a.RootElement.GetProperty("pos").GetInt64();
                    _posBan = b.RootElement.GetProperty("pos").GetInt64();
                    var items = new List<(double ts, JsonElement e, bool msg)>();
                    foreach (var e in a.RootElement.GetProperty("eventos").EnumerateArray()) items.Add((e.GetProperty("ts").GetDouble(), e.Clone(), false));
                    foreach (var m in b.RootElement.GetProperty("mensajes").EnumerateArray()) items.Add((m.GetProperty("ts").GetDouble(), m.Clone(), true));
                    foreach (var it in items.OrderBy(x => x.ts))
                    {
                        if (it.msg) VivoMensaje(it.e); else VivoEvento(it.e);
                    }
                    _vivoPrimera = false;
                    VivoEstado();
                }
            }
            catch { _vivoEstado.Text = "Sin conexión con el servidor"; }
            finally { _vivoOcupado = false; }
        }

        private void VivoAgregar(UIElement el)
        {
            bool final = _vivoScroll.VerticalOffset + _vivoScroll.ViewportHeight >= _vivoScroll.ExtentHeight - 40 || _vivoPrimera;
            _vivoLista.Children.Add(el);
            while (_vivoLista.Children.Count > 400) _vivoLista.Children.RemoveAt(0);
            if (final) Dispatcher.BeginInvoke(new Action(() => _vivoScroll.ScrollToEnd()), DispatcherPriority.Background);
        }

        private void VivoEvento(JsonElement e)
        {
            _vivoActividad = true;
            if (e.TryGetProperty("ts", out var ts) && ts.ValueKind == JsonValueKind.Number) _vivoUltima = Math.Max(_vivoUltima, ts.GetDouble());
            var tipo = Texto(e, "t");
            var id = Texto(e, "id");
            if (tipo == "inicio")
            {
                var c = TarjetaTool.Crear(_t, Texto(e, "tool"), e.TryGetProperty("args", out var a) ? ResumenArgs(a) : "");
                _vivoTarjetas[id] = c;
                _vivoAbiertas++;
                VivoAgregar(c.Raiz);
            }
            else if (tipo == "fin")
            {
                if (!_vivoTarjetas.TryGetValue(id, out var c))
                {
                    c = TarjetaTool.Crear(_t, Texto(e, "tool"), "");
                    VivoAgregar(c.Raiz);
                }
                else { _vivoAbiertas = Math.Max(0, _vivoAbiertas - 1); _vivoTarjetas.Remove(id); }
                bool ok = e.TryGetProperty("ok", out var o) && o.ValueKind == JsonValueKind.True;
                var ms = e.TryGetProperty("ms", out var m) && m.ValueKind == JsonValueKind.Number ? m.GetInt32() : 0;
                c.Resolver(_t, ok, Texto(e, "texto"), ms >= 1000 ? (ms / 1000.0).ToString("0.0") + " s" : ms + " ms");
            }
        }

        private void VivoMensaje(JsonElement m)
        {
            bool mio = Texto(m, "de") == "usuario";
            var tipo = Texto(m, "tipo");
            Brush borde = tipo == "pregunta" ? _t.Aviso : tipo == "aviso" ? _t.Mal : tipo == "listo" ? _t.Ok : _t.Borde;
            var quien = new TextBlock { Text = mio ? "TÚ" : "TU AGENTE" + (tipo.Length > 0 && tipo != "info" ? " · " + tipo.ToUpperInvariant() : ""), FontSize = 10, Foreground = _t.Suave };
            var cuerpo = new TextBlock { Text = Texto(m, "texto"), TextWrapping = TextWrapping.Wrap, Foreground = _t.Texto };
            var pila = new StackPanel(); pila.Children.Add(quien); pila.Children.Add(cuerpo);
            VivoAgregar(Burbuja(pila, mio ? _t.Usuario : _t.Tarjeta, mio ? Brushes.Transparent : borde, mio ? HorizontalAlignment.Right : HorizontalAlignment.Left));
        }

        private void VivoEstado()
        {
            var hace = _vivoUltima > 0 ? (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0) - _vivoUltima : -1;
            if (_vivoAbiertas > 0) _vivoEstado.Text = "Tu agente está trabajando…";
            else if (hace >= 0 && hace < 120) _vivoEstado.Text = "Tu agente está en espera (última acción hace " + (int)hace + " s)";
            else _vivoEstado.Text = _vivoActividad ? "Sin actividad reciente" : "Esperando a tu agente…";
            _vivoAyuda.Visibility = _vivoActividad ? Visibility.Collapsed : Visibility.Visible;
        }
    }
}
