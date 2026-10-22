# Pruebas pendientes (plugin 1.17.0 y 1.18.0)

Todo lo de estos dos lotes **compila contra AutoCAD 2019-2027** (`python tools/matriz_api.py`) y pasa las
suites sin AutoCAD, pero **no se probó en vivo**. Lo hecho mientras no había nadie frente a la máquina.

## Cómo probarlo (unos minutos, con AutoCAD 2022 o 2027)

1. Cerrar AutoCAD (guardar lo que tenga abierto).
2. Instalar el plugin nuevo:
   ```powershell
   powershell -File tools/install_bundle.ps1 -CloseAutoCad -Reopen
   ```
3. Con AutoCAD abierto y el plugin cargado (`ping` debe decir `1.18.0`):
   ```bash
   python mcp_server/verificar_lote_1_17.py
   ```
   Trabaja en un dibujo nuevo descartable y lo cierra. Imprime una línea por comprobación y, al final,
   cuáles fallaron.
4. Después, las baterías de siempre, para confirmar que nada se rompió:
   ```bash
   python mcp_server/verificar_version.py
   python mcp_server/prueba_crear_objetos.py
   python mcp_server/prueba_navegacion.py
   ```

## Qué cubre `verificar_lote_1_17.py`

purga, capa actual, grupos, XData, datos propios (Xrecord), atributos de bloque, escalas de anotación,
impresión de layouts (PlotSettingsValidator), bloques dinámicos (solo que no caiga en uno estático), estilos
de tabla y de directriz, **fusionar / borrar / aislar capas, estados de capa nativos, capas por viewport,
copiar y renombrar láminas, export_copy DWG/DXF, propiedades del dibujo, explode / break / divide /
boundary / match_properties, rectángulo / polígono / elipse / líneas de construcción / punto, y sólidos por
extrusión / revolución / barrido / loft**.

## Lo que NO cubre y conviene mirar a mano

- `bind_xref` / `unload_xref` con un xref de verdad (el script solo prueba los rechazos).
- `set_dynamic_block_properties` sobre un bloque dinámico real (hace falta un DWG con uno).
- `restore_layer_state(turn_off_others=True)`: la política «1 = apagar» salió de leer la firma.
- `create_ellipse`, `create_construction_line`: dependen de que `create_object` acepte esos tipos.
- Una 2023-2026 (solo se compiló; las probadas en vivo son 2022 y 2027).

## Un test que depende de AutoCAD sin querer

`mcp_server/test_acabados_3d.py` llama a `layers.ensure` y necesita un AutoCAD abierto (falla con «No se pudo
conectar» si está cerrado, y si está abierto dibuja capas en el plano activo). Está pendiente de mockearlo.
