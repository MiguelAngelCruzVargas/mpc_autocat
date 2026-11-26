# Cómo usar la IA con Vigentra Architech

Architech funciona con IA, y hay **tres formas** de dársela. Puedes cambiar de una a otra cuando quieras desde el
chat de AutoCAD (comando `MCPCHAT` → ⚙ Ajustes → IA).

| Forma | Qué necesitas | Para quién |
|---|---|---|
| **1. IA incluida en tu plan** | Nada: tu licencia de Architech | Quien no tiene cuenta con ningún proveedor de IA |
| **2. Tu propia clave de API** | Una clave de OpenAI, Anthropic, OpenRouter, Groq, DeepSeek... | Quien ya paga una API y quiere elegir el modelo |
| **3. Tu suscripción** (Claude o ChatGPT) | Claude Code o Codex instalados | Quien ya paga Claude Pro/Max o ChatGPT Plus/Pro |

> Las suscripciones de ChatGPT o Claude **no** traen acceso por API: por eso no se pueden pegar como «clave».
> Se usan con su propio programa (Claude Code o Codex), en la forma 3.

## 1. IA incluida en tu plan

En el chat de AutoCAD, en **IA**, elige **«IA INCLUIDA EN TU PLAN»** (es la primera). No pide clave: usa tu licencia.

- Cada plan trae un crédito mensual de IA; el chat te dice cuánto te queda («te quedan US$X este mes»).
- El crédito se renueva el día 1 de cada mes. La prueba gratis de 7 días trae el suyo.
- Si se te acaba, puedes seguir con tu propia clave (forma 2) o pedir un paquete de crédito a Vigentra.
- El tope de gasto por pedido (⚙ Ajustes → Tope de gasto) también funciona con la IA incluida.

## 2. Tu propia clave de API

En **IA**, elige el proveedor (OpenAI, Anthropic, OpenRouter...), pega tu clave en **Clave de API** y pulsa
**Guardar**. Se guarda cifrada en tu usuario de Windows y no se manda a Vigentra. El gasto lo cobra tu proveedor.

## 3. Tu suscripción de Claude o ChatGPT (modo «En vivo»)

Tu agente trabaja en su propio programa, con tu suscripción, usando las herramientas de Architech; el chat de AutoCAD
te muestra en vivo cada herramienta que usa y te deja mandarle mensajes.

1. Instala el agente:
   - **Claude** (Pro o Max): [Claude Code](https://claude.com/claude-code).
   - **ChatGPT** (Plus o Pro): [Codex](https://developers.openai.com/codex). Su configuración la comparten la
     terminal, la extensión del editor y Codex en la app de ChatGPT.
2. Conéctalo **una sola vez** a Architech. El instalador lo hace solo si detecta el agente; si no, en el chat elige
   **«En vivo · tu agente»** y copia el comando que aparece. Es así:
   - Claude Code: `claude mcp add autocad -s user -- "<python>" "<carpeta de Architech>\mcp_server\server.py"`
   - Codex: `codex mcp add autocad -- "<python>" "<carpeta de Architech>\mcp_server\server.py"`
3. Con AutoCAD abierto, trabaja con tu agente en su programa («dibuja la planta de una casa de 8 x 20...»).

También funcionan Claude Desktop y OpenCode: el instalador los registra si los encuentra.

### Lo que todavía no se puede

- **El chat normal de ChatGPT** (sin Codex) no carga herramientas locales: usa Codex o las formas 1 y 2.
- **El asistente de Autodesk** de AutoCAD 2027 trae su propio servidor MCP, pero Autodesk no documenta cómo
  agregarle herramientas de terceros. Cuando lo abra, Architech se conectará ahí también.

## Modo análisis (revisar un plano sin modificarlo)

En cualquiera de las tres formas, elige la especialidad **«Análisis»** o adjunta un PDF con el clip 📎. El chat:

- describe qué contiene el plano y te pregunta cuál es tu duda;
- fundamenta cada observación: norma (solo las que el sistema tiene respaldadas, con su artículo y estatus),
  práctica constructiva o cálculo;
- si le dices «está mal», primero lo comprueba y después te da o te quita la razón, con fundamento;
- no modifica nada: propone el cambio y te pregunta antes de aplicarlo.

Para revisar las imágenes de un PDF usa un modelo que vea imágenes (por ejemplo Claude o GPT con visión).
