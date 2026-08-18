using System;
using System.Collections.Concurrent;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Cola de trabajos para marshalizar llamadas del hilo del socket al hilo
    /// principal de AutoCAD, enganchada al evento Application.Idle.
    ///
    /// Reemplaza a ExecuteInCommandContextAsync: en la práctica ese callback no
    /// siempre se dispara (quedaba colgado el cliente TCP esperando para
    /// siempre), mientras que Application.Idle es el patrón clásico y confiable
    /// para esto.
    /// </summary>
    public static class MainThreadQueue
    {
        private static readonly ConcurrentQueue<Action> _queue = new ConcurrentQueue<Action>();
        private static bool _hooked;

        public static void EnsureHooked()
        {
            if (_hooked) return;
            Application.Idle += OnIdle;
            _hooked = true;
        }

        public static void Post(Action action)
        {
            _queue.Enqueue(action);
        }

        private static void OnIdle(object sender, EventArgs e)
        {
            while (_queue.TryDequeue(out var action))
            {
                action();
            }
        }
    }
}
