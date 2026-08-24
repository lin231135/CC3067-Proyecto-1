# CC3067 - Proyecto 1: Uso de un protocolo existente (MCP)

Universidad del Valle de Guatemala -- CC3067 Redes -- Sección 20

> **Nota:** este archivo es una traducción al español para referencia
> propia. El archivo [`README.md`](README.md) (en inglés) es la
> documentación oficial del proyecto, tal como lo exige el enunciado.

Este repositorio implementa el **Model Context Protocol (MCP)** para el
Proyecto 1. Eventualmente contendrá un chatbot completo (el "anfitrión")
que combina servidores MCP oficiales (Filesystem, Git) con un servidor MCP
propio, local y remoto. **Esta entrega es el avance parcial que pide el
enunciado: únicamente el servidor MCP local**, implementado desde cero
sobre JSON-RPC 2.0, sin usar ningún SDK de MCP (nada de FastMCP ni
similares).

## Caso de uso: LIMS para un laboratorio de análisis de alimentos

El servidor modela un sistema de gestión de laboratorio (LIMS) para un
laboratorio que recibe muestras de alimentos (de plantas procesadoras,
restaurantes, exportadoras, etc.) y realiza análisis fisicoquímicos y
microbiológicos (pH, coliformes fecales, Salmonella, recuento de aerobios
totales, humedad, actividad de agua, Staphylococcus aureus, E. coli,
Listeria, mohos y levaduras). Un chatbot conectado a este servidor le
permitiría al personal del laboratorio preguntar cosas como:

- *"¿Qué muestras de Alimentos del Sur están pendientes de resultado?"*
- *"Registra una nueva muestra de leche de Lácteos San Miguel para
  análisis de pH y Salmonella."*
- *"Dame el reporte de la muestra LIMS-2026-0032."*

Especificación completa, esquemas de cada herramienta y ejemplos de uso:
[`docs/lims_mcp_server_spec.md`](docs/lims_mcp_server_spec.md) (en
inglés).

## Funcionalidades implementadas en esta entrega

- Un ciclo de mensajes JSON-RPC 2.0 hecho a mano sobre **stdio**
  (`lims_mcp_server/server.py`, `jsonrpc.py`): no se usa ningún SDK de
  MCP, todo el framing/parseo/despacho de mensajes es manual.
- El ciclo de vida de MCP: `initialize`, `notifications/initialized`,
  `ping`.
- Descubrimiento de herramientas (`tools/list`) e invocación
  (`tools/call`), con `inputSchema` (JSON Schema) para cada herramienta.
- Cinco herramientas del dominio (`lims_mcp_server/tools.py`):
  `register_sample`, `get_sample_status`, `get_analysis_results`,
  `list_pending_samples`, `generate_report_summary`.
- Una base de datos SQLite (solo `sqlite3` de la librería estándar, sin
  ORM) con tablas `clients`, `samples`, `analysis_parameters`, `results`.
- Un generador de datos sintéticos (`lims_mcp_server/seed.py`) que puebla
  entre 50 y 100 muestras realistas repartidas en 10 clientes.
- Un cliente de prueba manual en JSON-RPC (`tests/manual_client.py`) que
  levanta el servidor y ejercita las 5 herramientas de principio a fin,
  imprimiendo el intercambio de protocolo crudo.

Lo que **no** forma parte de esta entrega (fases posteriores del
proyecto, según el enunciado): el chatbot/anfitrión en sí, la integración
con los servidores oficiales Filesystem/Git MCP, el despliegue remoto
(Cloud Run) de este mismo servidor, y el análisis de tráfico con
Wireshark.

## Requisitos

- Python 3.10 o superior
- Sin dependencias externas: todo lo usado (`json`, `sqlite3`, `sys`,
  `argparse`, `datetime`, `random`, `subprocess`) es parte de la
  librería estándar de Python.

## Instalación

```bash
git clone https://github.com/lin231135/CC3067-Proyecto-1.git
cd CC3067-Proyecto-1
```

No es estrictamente necesario un entorno virtual ni `pip install` porque
no hay dependencias de terceros, pero puedes crear uno si prefieres:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
```

## Uso

### 1. Poblar la base de datos con datos de demo

Ejecuta esto una vez (o cuando quieras reiniciar los datos de demo):

```bash
python -m lims_mcp_server.seed --samples 80
```

Esto crea `data/lims.db` con 10 clientes, el catálogo de 10 parámetros de
análisis, y 80 muestras en una mezcla realista de estados `received` /
`in_analysis` / `finalized`.

Opciones: `--samples N` (por defecto 80, el rango válido para el caso de
uso es 50-100) y `--seed N` (semilla aleatoria, por defecto 42, para
reproducibilidad).

### 2. Ejecutar el cliente de demo automatizado

La forma más fácil de ver el servidor funcionando de principio a fin
(handshake, descubrimiento de herramientas, y las 5 herramientas,
incluyendo el caso de error con una muestra que no existe) es:

```bash
python tests/manual_client.py
```

Imprime cada mensaje JSON-RPC enviado (`>>`) y recibido (`<<`).

### 3. Ejecutar el servidor por sí solo

```bash
python -m lims_mcp_server.server
```

El servidor espera solicitudes JSON-RPC 2.0 por stdin y escribe las
respuestas en stdout (los logs de diagnóstico van a stderr). Puedes
manejarlo manualmente escribiendo mensajes JSON-RPC, uno por línea, por
ejemplo:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "manual", "version": "0.1"}}}
{"jsonrpc": "2.0", "method": "notifications/initialized"}
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_pending_samples", "arguments": {}}}
```

Presiona `Ctrl+D` (macOS/Linux) o `Ctrl+Z` y luego Enter (Windows) para
cerrar stdin y detener el servidor.

### 4. (Opcional) Verificar con Claude Desktop

Como sugiere el enunciado, también puedes apuntar Claude Desktop a este
servidor para confirmar que se comporta como un proveedor de
herramientas MCP real. Agrega esto a tu `claude_desktop_config.json`
(ajusta la ruta a tu clon del repositorio):

```json
{
  "mcpServers": {
    "lims-food-analysis": {
      "command": "python",
      "args": ["-m", "lims_mcp_server.server"],
      "cwd": "C:/github/CC3067-Proyecto-1"
    }
  }
}
```

Reinicia Claude Desktop y pregúntale algo como *"¿Qué muestras de
alimentos están pendientes de resultado?"* -- debería invocar
`list_pending_samples` automáticamente.

## Estructura del proyecto

```
CC3067-Proyecto-1/
|-- lims_mcp_server/
|   |-- server.py        # loop stdin/stdout JSON-RPC (punto de entrada)
|   |-- jsonrpc.py        # lectura/escritura de mensajes JSON-RPC 2.0 + códigos de error
|   |-- protocol.py       # handlers de métodos MCP (initialize, tools/list, tools/call)
|   |-- tools.py          # las 5 herramientas del dominio + sus JSON Schemas
|   |-- database.py       # manejo de la conexión SQLite
|   |-- schema.sql         # definición de tablas
|   `-- seed.py           # generador de datos sintéticos de demo
|-- tests/
|   `-- manual_client.py  # script de prueba/demo JSON-RPC de punta a punta
|-- docs/
|   `-- lims_mcp_server_spec.md  # especificación completa del protocolo/herramientas
|-- data/                 # aquí se crea data/lims.db (ignorado por git)
|-- README.md             # documentación oficial (en inglés, requerido por el enunciado)
`-- README.es.md          # este archivo
```

## Notas de diseño

- **Sin SDK de MCP.** Según lo exige el enunciado, el protocolo está
  implementado a mano: `jsonrpc.py` maneja el framing crudo de mensajes y
  los códigos de error de JSON-RPC 2.0, `protocol.py` implementa la
  semántica específica de MCP (`initialize`, `tools/list`, `tools/call`),
  y `server.py` los conecta con stdio.
- **Errores de herramienta vs. errores de protocolo.** Un código de
  muestra inválido o inexistente se reporta dentro de un resultado normal
  de `tools/call` (`isError: true`), no como un error de JSON-RPC --
  esto sigue la convención de MCP para que el LLM anfitrión pueda ver el
  fallo y reaccionar en la conversación.
- **Framing de stdio.** Cada mensaje JSON-RPC ocupa exactamente una
  línea; el servidor nunca escribe nada que no sea un mensaje de
  protocolo en stdout, por eso los logs van a stderr.

## Integridad académica

Desarrollado individualmente para CC3067 - Redes, UVG. No se usó ninguna
librería o SDK de MCP de terceros, según lo exige el enunciado.
