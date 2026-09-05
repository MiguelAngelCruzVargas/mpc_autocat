# Usar este MCP con cualquier IA, no solo Claude Code

El servidor MCP de este repo nunca supo quién lo llama: habla MCP por stdio
y nada más. Lo que ataba el proyecto a Claude Code no era el servidor — era
que faltaba el **host**, el proceso que lanza el servidor, le pide el
catálogo de tools, se lo traduce a un modelo y ejecuta lo que ese modelo
pide. Eso es lo que hay acá.

```
    tu instrucción
         │
    ┌────▼─────┐   HTTP    ┌──────────────┐
    │  agent   │──────────▶│  el modelo   │  OpenRouter, OpenAI, Groq,
    │  (host)  │◀──────────│  que elijas  │  DeepSeek, local, Anthropic…
    └────┬─────┘  "llamá   └──────────────┘
         │        create_walls(...)"
         │ MCP (stdio)
    ┌────▼─────────┐  TCP   ┌──────────┐
    │ mcp_server   │───────▶│ AutoCAD  │
    └──────────────┘        └──────────┘
```

## Empezar

```bash
# 1. La clave del proveedor (una sola vez)
setx OPENROUTER_API_KEY "sk-or-..."

# 2. Con AutoCAD abierto y el plugin cargado:
python -m agent.cli --proveedor openrouter --modelo anthropic/claude-3.5-sonnet

# Una sola instrucción, sin conversación:
python -m agent.cli --proveedor deepseek -p "dibujá una casa de 3 recámaras en un lote de 8x16"
```

## Proveedores

Se habla HTTP directo, sin el SDK de OpenAI: el formato
`/chat/completions` con `tools` es el mismo en todos, así que un solo
adaptador los cubre y el proyecto no queda atado a ninguno.

| `--proveedor` | Variable de entorno | Notas |
|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | Cientos de modelos con una sola clave |
| `openai` | `OPENAI_API_KEY` | |
| `groq` | `GROQ_API_KEY` | Muy rápido, modelos abiertos |
| `deepseek` | `DEEPSEEK_API_KEY` | Barato |
| `together` | `TOGETHER_API_KEY` | |
| `anthropic` | `ANTHROPIC_API_KEY` | Formato propio (no el de OpenAI) |
| `local` | — | LM Studio / Ollama en `localhost:1234` |

Cualquier otro endpoint compatible: `--url http://donde-sea/v1 --modelo x`.

## El perfil de tools NO es un detalle

Son 131 tools. Las definiciones solas, medidas (conteos reales, no la
cantidad de patrones — un perfil se define por prefijos como `create_` o
`check_`, así que "Civil (37 tools)" en la interfaz sale de contar contra
el catálogo real del servidor, no de contar líneas en `PERFILES`):

| Perfil | Tools | ~tokens por vuelta |
|---|---:|---:|
| `basico` | 24 | 6 200 |
| `estructura` | 24 | 10 500 |
| `civil` | 37 | 14 800 |
| `arquitectura` (default) | 59 | 21 000 |
| `todo` | 131 | **45 900** |

Y el system prompt con `CLAUDE.md` (las reglas de dibujo del proyecto)
suma ~11 000 tokens más. O sea: `--perfil todo` cuesta ~57k tokens **en
cada vuelta del bucle**, y una casa entera son decenas de vueltas.

Por eso el default es `arquitectura`. Para un modelo de ventana corta o
para abaratar:

```bash
--limite-descripcion 200   # ~21k -> ~10k tokens de tools
--sin-reglas               # saca CLAUDE.md (el modelo dibuja peor)
--limite-reglas 12000      # o solo la primera parte
```

Recortar las descripciones tiene un costo real: los docstrings de este
repo son largos a propósito — explican por qué un muro no es una línea o
dónde va el cajón. Un modelo que no los lee dibuja peor.

## Qué esperar de cada modelo

El cuello de botella no es dibujar, es **encadenar**: un plano son decenas
de llamadas donde cada una depende de lo que devolvió la anterior. Los
modelos que hacen bien function calling en cadena (Claude, GPT-4o,
DeepSeek, Qwen grande) llegan a un plano completo; los chicos suelen
resolver una tool suelta y perderse en la tercera.

Dos cosas ayudan mucho a un modelo flojo:

- Empezar por `suggest_layout` + `draw_layout`: una llamada dibuja la casa
  entera, en vez de cuarenta llamadas a `create_walls`.
- `--perfil basico` para tareas simples: menos opciones, menos confusión.

## Cómo está armado

| Archivo | Qué hace |
|---|---|
| `mcp_link.py` | Lanza el servidor MCP y traduce su catálogo |
| `providers.py` | Habla con el modelo (formato OpenAI o Anthropic) |
| `loop.py` | El bucle: pedir → ejecutar tools → devolver resultado |
| `cli.py` | La interfaz de consola y los perfiles |
| `test_agent.py` | `python -m agent.test_agent` — no necesita clave |

Dos decisiones que valen la pena conocer si vas a tocarlo:

- **Los `anyOf` se aplanan.** FastMCP genera `{"anyOf": [{"type":"number"},
  {"type":"null"}]}` para cada `Optional[float]`. Varios modelos que no son
  de OpenAI lo ignoran y mandan un string donde va un número, o rechazan la
  tool. El dato de que es opcional no se pierde: vive en `required`.
- **Los errores de tool vuelven al modelo como texto, no como excepción.**
  Este servidor escribe sus errores para que se puedan corregir ("el hueco
  se sale del muro, que mide 10"). Un modelo que lee eso corrige y sigue;
  un bucle que se cae pierde la sesión entera.

## Interfaz web (sin consola)

`python iniciar.py` levanta `agent/web.py` — un server HTTP local
(`http://127.0.0.1:8770`, solo 127.0.0.1) que abre el navegador solo. Ahí
se configura el proveedor y la API key (cifrada con DPAPI en Windows,
0600 en Linux/macOS), se elige perfil y modelo, hay plantillas rápidas
por dominio, un visor del plano (captura real de AutoCAD, con zoom y
descarga PNG) y streaming del chat por Server-Sent Events — se ve cada
tool a medida que corre, no se espera a que termine todo el plano.

Para arrancarlo **sin ninguna ventana de consola** (pensado para quien no
use Claude Code y solo quiera el copiloto con una API más barata): doble
clic en `AutoCAD-IA.vbs` en la raíz del repo. Internamente llama a
`tools/lanzar_silencioso.bat`, que usa `pythonw.exe` y manda toda la
salida a `autocad-ia.log` (ya no hay pantalla donde mostrarla). Para
apagarlo: el botón "Apagar" dentro de la interfaz — no queda ninguna
ventana que cerrar. Si algo no arranca, `autocad-ia.log` tiene lo que
antes se veía en la consola negra.

## Lo que todavía no hace

- No hay confirmación antes de dibujar. El agente modifica el DWG abierto
  directamente — trabajá sobre una copia hasta que le tengas confianza al
  modelo que estés usando.
- Las plantillas rápidas y el chequeo de conexión con AutoCAD
  (`/api/autocad_estado`) están probados en vivo; el flujo de "adjuntar
  una imagen de referencia y que el agente pregunte lo ambiguo antes de
  dibujar" (la regla ya está en `SYSTEM_BASE`, en `cli.py`) todavía NO se
  probó de punta a punta contra AutoCAD real — hace falta AutoCAD abierto
  y un modelo multimodal para esa prueba.
- Casa completa de 4 recámaras / 2 baños: el prompt quedó armado, no se
  llegó a mandar por falta de AutoCAD conectado en esa sesión. El de 3
  recámaras (preset "Distribución Arquitectónica") sí está probado
  extremo a extremo.
- La rama `mcp-generacion-y-calidad` sigue sin mergear a `main`.
