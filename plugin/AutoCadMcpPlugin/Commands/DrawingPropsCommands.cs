using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using AcException = Autodesk.AutoCAD.Runtime.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Propiedades del dibujo (el cuadro «Propiedades del dibujo» / DWGPROPS): título, asunto, autor, palabras
    /// clave, comentarios, base de hipervínculos y propiedades personalizadas. Son lo que el Explorador de
    /// Windows muestra del archivo y lo que las listas de planos leen sin abrirlo: sirven para que cada DWG
    /// entregado diga de qué proyecto y de quién es.
    /// </summary>
    public static class DrawingPropsCommands
    {
        private static readonly string[] Campos = { "title", "subject", "author", "keywords", "comments", "hyperlink_base" };

        private static JsonObject Leer(DatabaseSummaryInfo si)
        {
            var custom = new JsonObject();
            var e = si.CustomProperties;
            while (e.MoveNext()) custom[Convert.ToString(e.Key)] = Convert.ToString(e.Value);
            return new JsonObject
            {
                ["title"] = si.Title, ["subject"] = si.Subject, ["author"] = si.Author, ["keywords"] = si.Keywords,
                ["comments"] = si.Comments, ["hyperlink_base"] = si.HyperlinkBase,
                ["last_saved_by"] = si.LastSavedBy, ["revision"] = si.RevisionNumber, ["custom"] = custom
            };
        }

        /// <summary>params: ninguno.</summary>
        public static JsonObject Get(Document doc, JsonObject pars)
        {
            return Leer(doc.Database.SummaryInfo);
        }

        /// <summary>params: [title], [subject], [author], [keywords], [comments], [hyperlink_base] (texto; "" lo vacía) y
        /// [custom] = {nombre: valor} (agrega o cambia; valor null borra la propiedad). Solo cambia lo que se pasa.</summary>
        public static JsonObject Set(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var b = new DatabaseSummaryInfoBuilder(db.SummaryInfo);
            int cambios = 0;
            foreach (var campo in Campos)
            {
                if (!pars.ContainsKey(campo) || pars[campo] == null) continue;
                string v = pars[campo].GetValue<string>();
                if (v.Length > 1000) throw new ArgumentException("'" + campo + "' no puede pasar de 1000 caracteres.");
                switch (campo)
                {
                    case "title": b.Title = v; break;
                    case "subject": b.Subject = v; break;
                    case "author": b.Author = v; break;
                    case "keywords": b.Keywords = v; break;
                    case "comments": b.Comments = v; break;
                    case "hyperlink_base": b.HyperlinkBase = v; break;
                }
                cambios++;
            }
            if (pars["custom"] is JsonObject custom)
            {
                if (custom.Count > 100) throw new ArgumentException("Máximo 100 propiedades personalizadas por llamada.");
                var tabla = b.CustomPropertyTable;
                foreach (var kv in custom)
                {
                    if (string.IsNullOrWhiteSpace(kv.Key) || kv.Key != kv.Key.Trim())
                        throw new ArgumentException("El nombre de una propiedad personalizada no puede estar vacío ni tener espacios en los bordes.");
                    if (kv.Key.Length > 255) throw new ArgumentException("El nombre de una propiedad personalizada no puede pasar de 255 caracteres.");
                    if (kv.Value == null)
                    {
                        if (tabla.Contains(kv.Key)) tabla.Remove(kv.Key);
                    }
                    else
                    {
                        string v = kv.Value.GetValue<string>();
                        if (v.Length > 1000) throw new ArgumentException("El valor de '" + kv.Key + "' no puede pasar de 1000 caracteres.");
                        tabla[kv.Key] = v;
                    }
                    cambios++;
                }
            }
            if (cambios == 0) throw new ArgumentException("No hay nada que cambiar: pasá title, subject, author, keywords, comments, hyperlink_base o custom.");
            try { db.SummaryInfo = b.ToDatabaseSummaryInfo(); }
            catch (AcException ex) { throw new InvalidOperationException("AutoCAD rechazó las propiedades (" + ex.ErrorStatus + "): " + ex.Message + "."); }
            return Leer(db.SummaryInfo);
        }
    }
}
