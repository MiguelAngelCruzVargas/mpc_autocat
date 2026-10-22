# Pruebas pendientes

## Hecho (22/10/2026)
Plugin 1.18.0 (incluye lo de 1.17.0) verificado en vivo en **AutoCAD 2022 y 2027**: `verificar_lote_1_17.py` 134/134, y las baterías de
siempre (`verificar_version` 31, `prueba_crear_objetos` 38, `prueba_navegacion` 26, `prueba_primitivas_3d` 16) en las dos.
Las pruebas encontraron dos CIERRES de AutoCAD (`RefreshLists` sobre un layout en lectura, y una `Ellipse` nula) y un orden inválido en `configure_layout` (centrado antes del tipo de área, ventana sin área), todo corregido.

## Falta
- Probar en vivo 2019-2021 y 2023-2026 (hoy solo compilan: `python tools/matriz_api.py`).
- `bind_xref` / `unload_xref` con un xref real (el script solo prueba los rechazos).
- `set_dynamic_block_properties` sobre un bloque dinámico real (hace falta un DWG con uno).
- `restore_layer_state(turn_off_others=True)`: la política «1 = apagar» salió de leer la firma.
- `test_acabados_3d.py` depende de AutoCAD sin querer (llama a `layers.ensure`): mockearlo.

## Cómo repetirlo
```powershell
powershell -File tools/install_bundle.ps1        # con AutoCAD cerrado
```
```bash
python mcp_server/verificar_lote_1_17.py         # dibujo nuevo descartable; sale con 1 si algo falla
```
Si AutoCAD se cierra o se cuelga: `diagnose_autocad` (o `python -c "import ojos; print(ojos.diagnostico()['conclusion'])"` desde `mcp_server`)
dice qué comando era, qué diálogo hay abierto y qué error dejó escrito.
