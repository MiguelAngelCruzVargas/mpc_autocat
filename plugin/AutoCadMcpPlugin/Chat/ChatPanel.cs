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
        private readonly TextBox _entrada = new TextBox();
        private readonly TextBlock _placeholder = new TextBlock();
        private readonly Button _enviar = new Button();
        private readonly PasswordBox _clave = new PasswordBox();
        private readonly TextBlock _claveEstado = new TextBlock();
        private readonly CheckBox _reglas = new CheckBox();
        private readonly Slider _temp = new Slider();
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
            FontSize = 12.5;
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
            var cab = new Grid { Margin = new Thickness(6, 6, 6, 6) };
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            cab.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            _provBtn.HorizontalContentAlignment = HorizontalAlignment.Stretch; _provBtn.Padding = new Thickness(8, 5, 8, 5);
            _provBtn.Click += (s, e) => AbrirAjustes();
            ActualizarChip();
            _ajustesBtn.Content = Icono("\uE713"); _ajustesBtn.ToolTip = "Configuración"; _ajustesBtn.Margin = new Thickness(4, 0, 0, 0); _ajustesBtn.Width = 32;
            _ajustesBtn.Click += (s, e) => { if (_ajustes.Visibility == Visibility.Visible) _ajustes.Visibility = Visibility.Collapsed; else AbrirAjustes(); };
            Grid.SetColumn(_ajustesBtn, 1);
            _nuevaBtn.Content = Icono("\uE710"); _nuevaBtn.ToolTip = "Conversación nueva"; _nuevaBtn.Margin = new Thickness(4, 0, 0, 0); _nuevaBtn.Width = 32;
            _nuevaBtn.Click += async (s, e) => await NuevaAsync().ConfigureAwait(true);
            Grid.SetColumn(_nuevaBtn, 2);
            cab.Children.Add(_provBtn); cab.Children.Add(_ajustesBtn); cab.Children.Add(_nuevaBtn);
            var cabBorde = new Border { Background = _t.Panel, BorderBrush = _t.Borde, BorderThickness = new Thickness(0, 0, 0, 1), Child = cab };
            Grid.SetRow(cabBorde, 0); raiz.Children.Add(cabBorde);

            // fila de contexto de AutoCAD: dibujo activo y selección
            var ctxFila = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(8, 0, 6, 4) };
            _ctxTexto.Foreground = _t.Suave; _ctxTexto.FontSize = 11; _ctxTexto.VerticalAlignment = VerticalAlignment.Center;
            _ctxTexto.TextTrimming = TextTrimming.CharacterEllipsis;
            _adjSel.Content = "adjuntar selección"; _adjSel.Foreground = _t.Texto; _adjSel.FontSize = 11; _adjSel.Margin = new Thickness(8, 0, 0, 0);
            _adjSel.VerticalAlignment = VerticalAlignment.Center; _adjSel.Visibility = Visibility.Collapsed;
            _adjSel.ToolTip = "Le manda al agente los handles y tipos de lo que tienes seleccionado en el dibujo";
            ctxFila.Children.Add(_ctxTexto); ctxFila.Children.Add(_adjSel);
            Grid.SetRow(ctxFila, 1); raiz.Children.Add(ctxFila);

            // contenido: conversación o vista «en vivo», y los ajustes encima
            var contenido = new Grid();
            _scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
            _scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
            _lista.Margin = new Thickness(6, 2, 6, 6);
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
            _estado.Foreground = _t.Suave; _estado.FontSize = 11; _estado.Margin = new Thickness(10, 2, 6, 2); _estado.TextTrimming = TextTrimming.CharacterEllipsis;


            // entrada
            ConstruirAvisoVivo();
            var ent = _entradaFila; ent.Margin = new Thickness(6, 4, 6, 6);
            ent.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            ent.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var caja = new Grid();
            EstilizarTexto(_entrada);
            _entrada.AcceptsReturn = true; _entrada.TextWrapping = TextWrapping.Wrap; _entrada.MinHeight = 34; _entrada.MaxHeight = 120;
            _entrada.VerticalScrollBarVisibility = ScrollBarVisibility.Auto; _entrada.Padding = new Thickness(6, 6, 6, 4);
            _entrada.PreviewKeyDown += async (s, e) =>
            {
                if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Shift) == 0) { e.Handled = true; await EnviarAsync().ConfigureAwait(true); }
            };
            _entrada.TextChanged += (s, e) => _placeholder.Visibility = _entrada.Text.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
            _placeholder.Text = "Escribe tu instrucción…"; _placeholder.Foreground = _t.Suave; _placeholder.IsHitTestVisible = false;
            _placeholder.Margin = new Thickness(10, 8, 0, 0); _placeholder.VerticalAlignment = VerticalAlignment.Top;
            caja.Children.Add(_entrada); caja.Children.Add(_placeholder);
            _enviar.Content = "Enviar"; _enviar.Margin = new Thickness(4, 0, 0, 0); _enviar.Padding = new Thickness(12, 3, 12, 3);
            _enviar.Background = _t.Acento; _enviar.Foreground = _t.AcentoTexto; _enviar.VerticalAlignment = VerticalAlignment.Stretch;
            _enviar.Click += async (s, e) => { if (_trabajando) Detener(); else await EnviarAsync().ConfigureAwait(true); };
            Grid.SetColumn(_enviar, 1);
            ent.Children.Add(caja); ent.Children.Add(_enviar);
            var pie = new Border { BorderBrush = _t.Borde, BorderThickness = new Thickness(0, 1, 0, 0), Background = _t.Panel, Child = new StackPanel { Children = { _estado, _vivoAviso, ent } } };
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

        private void ActualizarChip()
        {
            var pila = new StackPanel();
            var fila = new Grid();
            fila.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            fila.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            string nombre = _prov == null ? "Elegir con qué IA trabajar" : _prov.Vivo ? "En vivo · tu agente" : _prov.Nombre.Replace(" · sin clave", "");
            fila.Children.Add(new TextBlock { Text = nombre, FontWeight = FontWeights.SemiBold, TextTrimming = TextTrimming.CharacterEllipsis });
            var flecha = Icono("\uE70D", 10); flecha.Margin = new Thickness(6, 0, 0, 0); Grid.SetColumn(flecha, 1);
            fila.Children.Add(flecha);
            pila.Children.Add(fila);
            string detalle = null, perfil = null;
            if (_prov != null && !_prov.Vivo)
            {
                detalle = _modelo.Text.Trim();
                perfil = TextoPerfil();
            }
            else if (_prov != null)
                detalle = "Tu agente trabaja en su programa; aquí ves lo que hace";
            if (!string.IsNullOrEmpty(detalle))
                pila.Children.Add(new TextBlock { Text = detalle, FontSize = 11, Foreground = _t.Suave, TextWrapping = TextWrapping.Wrap });
            if (perfil != null)
                pila.Children.Add(new TextBlock { Text = perfil, FontSize = 11, Foreground = _t.Suave, TextWrapping = TextWrapping.Wrap });
            _provBtn.Content = pila;
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
                _listaPerfiles.Children.Add(Fila(item.id, item.tools + " herramientas" + (item.id == "todo" ? " (las 300; gasta muchos tokens por mensaje)" : item.id == "basico" ? " (dibujo simple)" : ""), item.id == _perfil, async () =>
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
                    if (pr.TryGetProperty("modelos", out var ms) && ms.ValueKind == JsonValueKind.Object)
                        foreach (var m in ms.EnumerateObject())
                            if (m.Value.ValueKind == JsonValueKind.String) _modelos[m.Name] = m.Value.GetString();
                }
                var elegido = _provs.FirstOrDefault(x => x.Id == prefProv) ?? _provs.FirstOrDefault(x => x.Clave && !x.Vivo) ?? _provs.FirstOrDefault();
                RefrescarPerfiles();
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
            _lista.Children.Add(new TextBlock
            {
                Text = "¿En qué te ayudo con este dibujo?", FontSize = 15, FontWeight = FontWeights.SemiBold, Foreground = _t.Texto, Margin = new Thickness(4, 8, 4, 2),
                TextWrapping = TextWrapping.Wrap,
            });
            _lista.Children.Add(new TextBlock
            {
                Text = "Puedo consultar, dibujar, revisar y cuantificar. Lo que veo en AutoCAD (el dibujo y tu selección) lo puedo usar.",
                Foreground = _t.Suave, Margin = new Thickness(4, 0, 4, 8), TextWrapping = TextWrapping.Wrap,
            });
            foreach (var s in new[] { "¿Qué hay en el dibujo abierto?", "Lista las capas del dibujo", "Revisa el plano con check_all" })
            {
                var texto = s;
                var b = new Button { Content = texto, HorizontalContentAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 0, 0, 4), Padding = new Thickness(8, 6, 8, 6) };
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
            using (var doc = await _cli.GetAsync("/api/historial").ConfigureAwait(true))
            {
                var eventos = doc.RootElement.GetProperty("eventos").EnumerateArray().ToList();
                if (eventos.Count == 0) return;
                QuitarSugerencias();
                foreach (var ev in eventos.Skip(Math.Max(0, eventos.Count - 120)))
                {
                    var tipo = Texto(ev, "tipo");
                    if (tipo == "usuario") AgregarUsuario(Texto(ev, "texto"));
                    else Procesar(ev);
                }
                AgregarNota("Conversación anterior restaurada. «＋» la borra.");
            }
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

        private Border Burbuja(UIElement contenido, Brush fondo, Brush borde, HorizontalAlignment lado)
        {
            return new Border
            {
                Background = fondo, BorderBrush = borde, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
                Padding = new Thickness(8, 5, 8, 6), Margin = new Thickness(lado == HorizontalAlignment.Right ? 28 : 0, 3, lado == HorizontalAlignment.Left ? 14 : 0, 3),
                HorizontalAlignment = lado == HorizontalAlignment.Right ? HorizontalAlignment.Stretch : HorizontalAlignment.Stretch, Child = contenido,
            };
        }

        private void AgregarUsuario(string texto, string adjunto = null)
        {
            // Lo que se restaura del servidor trae el bloque «[Contexto de AutoCAD]...» pegado al mensaje: se separa
            // para no mostrar la lista de handles en la burbuja.
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
            var pila = new StackPanel();
            pila.Children.Add(new TextBlock { Text = texto, TextWrapping = TextWrapping.Wrap, Foreground = _t.Texto, FontSize = 12.5 });
            if (adjunto != null)
                pila.Children.Add(new TextBlock { Text = adjunto, Foreground = _t.Suave, FontSize = 11, Margin = new Thickness(0, 3, 0, 0) });
            Agregar(Burbuja(pila, _t.Usuario, Brushes.Transparent, HorizontalAlignment.Right));
        }

        private void AgregarAsistente(string texto)
        {
            var b = Burbuja(ChatMarkdown.Render(texto, _t), _t.Tarjeta, _t.Borde, HorizontalAlignment.Left);
            var copiar = new MenuItem { Header = "Copiar" };
            copiar.Click += (s, e) => { try { Clipboard.SetText(texto); } catch { } };
            b.ContextMenu = new ContextMenu { Items = { copiar } };
            Agregar(b);
        }

        private void AgregarAviso(string texto)
        {
            Agregar(new Border
            {
                BorderBrush = _t.Mal, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(8, 5, 8, 5), Margin = new Thickness(0, 3, 0, 3),
                Child = new TextBlock { Text = texto, TextWrapping = TextWrapping.Wrap, Foreground = _t.Mal },
            });
        }

        private void AgregarNota(string texto) =>
            Agregar(new TextBlock { Text = texto, Foreground = _t.Suave, FontSize = 11, Margin = new Thickness(4, 6, 4, 6), TextWrapping = TextWrapping.Wrap });

        // Una herramienta en la lista: ⏳ corriendo → ✓ / ✗, con el resumen de sus argumentos y, al hacer clic, su resultado.
        internal sealed class TarjetaTool
        {
            public Border Raiz;
            public TextBlock Icono, Detalle, Resumen, Extra;
            public string Nombre;
            public bool Abierta;
            public string Completo = "", Corto = "";

            public static TarjetaTool Crear(ChatTema t, string nombre, string args)
            {
                var c = new TarjetaTool { Nombre = nombre };
                var g = new Grid();
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(20) });
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                for (int i = 0; i < 4; i++) g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                c.Icono = new TextBlock { Text = "⏳", Foreground = t.Suave };
                var nom = new TextBlock { Text = nombre, FontFamily = new FontFamily("Consolas"), FontWeight = FontWeights.SemiBold, Foreground = t.Texto, TextWrapping = TextWrapping.Wrap };
                Grid.SetColumn(nom, 1);
                c.Detalle = new TextBlock { Text = args, FontFamily = new FontFamily("Consolas"), FontSize = 11, Foreground = t.Suave, TextWrapping = TextWrapping.Wrap };
                Grid.SetColumn(c.Detalle, 1); Grid.SetRow(c.Detalle, 1);
                if (string.IsNullOrEmpty(args)) c.Detalle.Visibility = Visibility.Collapsed;
                // lo que contestó la herramienta, a la vista (unas líneas); el detalle completo, al hacer clic
                c.Resumen = new TextBlock { FontFamily = new FontFamily("Consolas"), FontSize = 11, Foreground = t.Texto, TextWrapping = TextWrapping.Wrap, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 3, 0, 0), MaxHeight = 64 };
                Grid.SetColumn(c.Resumen, 1); Grid.SetRow(c.Resumen, 2);
                c.Extra = new TextBlock { FontFamily = new FontFamily("Consolas"), FontSize = 11, Foreground = t.Texto, TextWrapping = TextWrapping.Wrap, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 3, 0, 0) };
                Grid.SetColumn(c.Extra, 1); Grid.SetRow(c.Extra, 3);
                g.Children.Add(c.Icono); g.Children.Add(nom); g.Children.Add(c.Detalle); g.Children.Add(c.Resumen); g.Children.Add(c.Extra);
                c.Raiz = new Border
                {
                    Background = t.Tarjeta, BorderBrush = t.Borde, BorderThickness = new Thickness(1, 1, 1, 1), CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(6, 4, 6, 4), Margin = new Thickness(0, 2, 14, 2), Child = g, Cursor = Cursors.Hand,
                };
                c.Raiz.MouseLeftButtonUp += (s, e) => { c.Abierta = !c.Abierta; c.Pintar(); };
                return c;
            }

            private void Pintar()
            {
                bool hay = Completo.Length > 0;
                bool largo = Completo.Length > Corto.Length;
                Resumen.Visibility = hay && !Abierta ? Visibility.Visible : Visibility.Collapsed;
                Extra.Visibility = hay && Abierta ? Visibility.Visible : Visibility.Collapsed;
                Resumen.Text = Corto + (largo ? "   ▸ clic para ver todo" : "");
            }

            public void Resolver(ChatTema t, bool ok, string texto, string tiempo)
            {
                Icono.Text = ok ? "✓" : "✗";
                Icono.Foreground = ok ? t.Ok : t.Mal;
                Raiz.BorderBrush = ok ? t.Borde : t.Mal;
                texto = texto ?? "";
                Completo = texto.Length > 3000 ? texto.Substring(0, 2997) + "…" : texto;
                var plano = System.Text.RegularExpressions.Regex.Replace(Completo, @"\s+", " ").Trim();
                Corto = plano.Length > 150 ? plano.Substring(0, 147) + "…" : plano;
                Extra.Text = Completo;
                Resumen.Foreground = ok ? t.Texto : t.Mal;
                if (!string.IsNullOrEmpty(tiempo)) Detalle.Text = (Detalle.Text.Length > 0 ? Detalle.Text + "  ·  " : "") + tiempo;
                if (Detalle.Text.Length > 0) Detalle.Visibility = Visibility.Visible;
                Pintar();
            }
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
                        var resumen = Texto(ev, "modelo") + (ev.TryGetProperty("tools", out var n) && n.ValueKind == JsonValueKind.Number ? " · " + n.GetInt32() + " herramientas (especialidad: " + _perfil + ")" : "");
                        AgregarNota("⚙ " + resumen);
                        _estado.Text = resumen + " · trabajando…";
                        break;
                    }
                case "texto":
                    AgregarAsistente(Texto(ev, "texto"));
                    break;
                case "tool":
                    {
                        var nombre = Texto(ev, "nombre");
                        var c = TarjetaTool.Crear(_t, nombre, ev.TryGetProperty("args", out var a) ? ResumenArgs(a) : "");
                        if (!_pendientes.TryGetValue(nombre, out var cola)) _pendientes[nombre] = cola = new Queue<TarjetaTool>();
                        cola.Enqueue(c);
                        Agregar(c.Raiz);
                        break;
                    }
                case "resultado":
                    {
                        var nombre = Texto(ev, "nombre");
                        bool error = ev.TryGetProperty("error", out var er) && er.ValueKind == JsonValueKind.True;
                        if (_pendientes.TryGetValue(nombre, out var cola) && cola.Count > 0)
                            cola.Dequeue().Resolver(_t, !error, Texto(ev, "texto"), null);
                        break;
                    }
                case "aviso":
                    AgregarAviso(Texto(ev, "texto"));
                    break;
                case "uso":
                    if (ev.TryGetProperty("total", out var tot) && tot.ValueKind == JsonValueKind.Number) _tokens = tot.GetInt32();
                    if (ev.TryGetProperty("vueltas", out var v) && v.ValueKind == JsonValueKind.Number) _vueltas = v.GetInt32();
                    if (ev.TryGetProperty("costoUSD", out var cu) && cu.ValueKind == JsonValueKind.Number) _costo = cu.GetDouble();
                    _estado.Text = _tokens.ToString("N0") + " tokens · " + _vueltas + " v." + (_costo > 0 ? " · US$" + _costo.ToString("0.0000") : "") + (_trabajando ? " · trabajando…" : "");
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
            QuitarSugerencias();
            AgregarUsuario(texto, sel > 0 ? "📎 " + sel + " entidad(es) de AutoCAD" : null);
            _entrada.Clear();
            _adjSel.IsChecked = false;

            _trabajando = true;
            _enviar.Content = "Detener";
            _estado.Text = "trabajando…";
            _cts = new CancellationTokenSource();
            try
            {
                await _cli.ChatAsync(new
                {
                    mensaje = contexto == null ? texto : contexto + "\n\n" + texto,
                    imagenes = new string[0],
                    proveedor = _prov.Id,
                    modelo = _modelo.Text.Trim(),
                    perfil = _perfil,
                    conReglas = _reglas.IsChecked == true,
                    temperatura = _temp.Value,
                    topeUSD = 0,
                    contexto = "",
                }, Procesar, _cts.Token).ConfigureAwait(true);
            }
            catch (ChatError e) { AgregarAviso(e.Message); }
            catch (OperationCanceledException) { }
            catch (Exception e) when (!_cts.IsCancellationRequested) { AgregarAviso("Se cortó la conexión: " + e.Message); }
            finally
            {
                _trabajando = false;
                _enviar.Content = "Enviar";
                foreach (var cola in _pendientes.Values) cola.Clear();
                var t = _estado.Text;
                if (t.EndsWith(" · trabajando…", StringComparison.Ordinal)) _estado.Text = t.Substring(0, t.Length - " · trabajando…".Length);
                else if (t == "trabajando…") _estado.Text = "";
            }
        }

        private void Detener()
        {
            try { _cts?.Cancel(); } catch { }
            if (_cli != null) _ = _cli.PostAsync("/api/cancelar", new { }).ContinueWith(t => { var _ = t.Exception; });
            AgregarNota("Detenido. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir.");
        }

        private async Task NuevaAsync()
        {
            if (_trabajando || _cli == null) return;
            try { using (await _cli.PostAsync("/api/reset", new { }).ConfigureAwait(true)) { } } catch { }
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
            _ctxTexto.Text = "📄 " + (string.IsNullOrEmpty(nombre) ? "(sin dibujo)" : nombre) + (n > 0 ? "  ·  " + n + " seleccionado(s)" : "");
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
