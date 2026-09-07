# Reporte Final

> Traducción al español para referencia. La versión oficial es
> [`REPORT.md`](REPORT.md) (en inglés).

CC3067 - Redes, UVG. Proyecto 1: Uso de un protocolo existente (MCP).

Este reporte cubre los puntos 8-10 del enunciado: la especificación de
los servidores MCP construidos para este proyecto, el análisis de
protocolo/capas basado en Wireshark, y las conclusiones. Resume y
enlaza a los documentos más detallados que ya existen en este
repositorio, en vez de duplicarlos.

## 1. Servidores desarrollados (punto 8 del enunciado)

Se construyeron dos servidores MCP para este proyecto, ambos
implementando el caso de uso LIMS (laboratorio de análisis de
inocuidad de alimentos) descrito en la propuesta original, compartiendo
exactamente la misma lógica de negocio (`lims_mcp_server/tools.py`,
`database.py`, `protocol.py`) sobre dos transportes distintos,
implementados a mano:

| | Servidor local | Servidor remoto |
|---|---|---|
| Transporte | stdio, JSON-RPC 2.0 delimitado por saltos de línea | Streamable HTTP + SSE |
| Punto de entrada | `python -m lims_mcp_server.server` | `python -m lims_mcp_server.http_server` |
| Dónde corre | La máquina del desarrollador, iniciado por el chatbot host | **En vivo**: `https://cc3067-lims-mcp.onrender.com` |
| Estado de sesión | Implícito (un proceso por conexión) | Header explícito `Mcp-Session-Id`, emitido en `initialize` |

La especificación completa -- las 5 tools (`register_sample`,
`get_sample_status`, `get_analysis_results`, `list_pending_samples`,
`generate_report_summary`), sus JSON Schemas, ejemplos de llamadas/
resultados, el catálogo de parámetros de análisis, y el modelo de
datos SQLite -- está en
[`lims_mcp_server_spec.es.md`](lims_mcp_server_spec.es.md). Los
endpoints del transporte HTTP + SSE (`POST /mcp`, `GET /health`, manejo
de sesión, códigos de error) están documentados en el
[README](../README.es.md#transporte-remoto-http--sse) principal. Los
pasos de despliegue (y por qué el servidor remoto terminó en Render en
vez del Google Cloud Run propuesto originalmente) están en
[`deployment.es.md`](deployment.es.md).

No se usó ningún SDK de MCP (p. ej. FastMCP) ni SDK de Anthropic en
ninguna parte del proyecto, según lo exige el enunciado:
`lims_mcp_server/jsonrpc.py`, `chatbot/mcp/jsonrpc_client.py`,
`chatbot/mcp/stdio_client.py`, `chatbot/mcp/http_client.py`, y
`chatbot/anthropic_client.py` implementan todos sus respectivos
protocolos a mano.

### Estado del proyecto al momento de este reporte

- [x] Servidor MCP local LIMS -- implementado, probado de punta a
      punta.
- [x] Chatbot host (API de Anthropic, contexto de sesión, log de
      interacciones, orquestación de Filesystem + Git + LIMS) --
      **verificado en vivo por completo** contra la API real de
      Anthropic (`claude-haiku-4-5-20251001`) y el servidor LIMS remoto
      realmente desplegado: el modelo eligió por sí solo llamar a
      `list_pending_samples` para una pregunta de LIMS, respondió el
      propio ejemplo de retención de contexto del enunciado ("¿Quién
      fue Alan Turing?" -> "¿En qué fecha nació?" sin repetir el
      nombre) usando el historial de mensajes de la misma sesión, y
      completó el escenario demo completo de punta a punta --
      `write_file` -> `git_add` -> `git_commit`, todas llamadas a
      tools iniciadas por el modelo, produciendo un commit de git real
      -- a través de los servidores oficiales Filesystem y Git MCP.
- [x] Transporte remoto (HTTP + SSE) para el mismo servidor --
      implementado, probado localmente, y **desplegado en vivo** en
      `https://cc3067-lims-mcp.onrender.com` (Render, no Cloud Run --
      ver "Dificultades" abajo). Verificado contra la URL real:
      `GET /health`, y una secuencia completa `initialize` -> handshake
      de sesión -> `tools/list` -> `tools/call` (casos de éxito y de
      error de no-encontrado), todo sobre HTTPS real.
- [x] Captura de Wireshark y clasificación de mensajes JSON-RPC --
      hecha **dos veces**: una vez localmente (loopback, texto plano,
      `docs/wireshark/local_capture.pcapng`) y una vez contra el
      servidor remoto realmente desplegado
      (`docs/wireshark/remote_capture.pcapng`, frame Ethernet real,
      enrutamiento IP real, handshake TLS real), así que el requisito
      del enunciado sobre el "servidor remoto" se cumple con una
      captura remota real, no solo con el sustituto local.

## 2. Análisis de Wireshark / capas OSI-TCP-IP (punto 9 del enunciado)

La tabla de clasificación completa, la evidencia de paquetes cruda, y
la explicación por capa están en
[`wireshark_analysis.es.md`](wireshark_analysis.es.md), obtenidas de
**dos** capturas reales: una local (loopback, texto plano) y una contra
el servidor remoto realmente desplegado
(`https://cc3067-lims-mcp.onrender.com`, red real, TLS real). Resumen
de los hallazgos por capa:

- **Capa de enlace:** la captura local (adaptador de loopback de
  Npcap) muestra un pseudo-header `Null/Loopback`, no un frame real --
  no hay salto de capa de enlace cuando ambos extremos son
  `127.0.0.1`. La captura remota (adaptador Wi-Fi real) muestra un
  frame **Ethernet II** genuino con direcciones MAC de origen/destino
  reales (la NIC de la laptop y el router de casa), confirmado
  directamente con `tshark -V`.
- **Capa de red:** la captura local es `127.0.0.1 -> 127.0.0.1` (sin
  enrutamiento real); la captura remota muestra enrutamiento IPv4
  real, `192.168.11.230` (la laptop, con NAT del router) ->
  `216.24.57.7` (el borde de Render con Cloudflare al frente para
  `cc3067-lims-mcp.onrender.com`, confirmado con `nslookup`).
- **Capa de transporte:** ambas capturas muestran el mismo patrón --
  cada uno de los 7 mensajes JSON-RPC enviados por
  `chatbot/mcp/http_client.py` abre su **propia** conexión TCP (sin
  reutilización keep-alive en `urllib`), cada una con su propio
  handshake de 3 vías (`SYN`/`SYN, ACK`/`ACK`), confirmado con
  `tshark -z conv,tcp` en ambos archivos. Una diferencia real: varias
  conexiones remotas se cierran con un `RST` de TCP en vez de un `FIN`
  elegante, consistente con que el CDN/proxy delante de Render cierra
  las conexiones `Connection: close` de corta duración de forma más
  agresiva que el servidor Python local.
- **Capa de aplicación:** localmente, tres framings anidados son
  directamente legibles en texto plano: HTTP (`POST /mcp`, códigos de
  estado, el header personalizado `Mcp-Session-Id`) llevando SSE
  (`event: message` / `data: ...`) llevando JSON-RPC 2.0
  (`"jsonrpc": "2.0"`, `id`/`method`/`result`). En la captura remota,
  `tshark -z io,phs` muestra una capa **TLS** entre TCP y donde estaría
  HTTP (59 de 130 frames): un handshake real (`ClientHello`/
  `ServerHello`) seguido de cada byte JSON-RPC viajando dentro de
  records TLS Application Data encriptados -- Wireshark ya no puede
  mostrar el contenido HTTP/JSON-RPC directamente, solo tamaño, tiempo,
  y dirección, que es el resultado esperado y correcto de desplegar
  sobre HTTPS.

Clasificación de mensajes (detalle completo y bytes crudos en
`wireshark_analysis.es.md`): `initialize` y
`notifications/initialized` son los mensajes de **sincronización** del
protocolo (handshake de capacidades/sesión antes de que empiece el
trabajo real); `tools/list` y cada `tools/call` son **solicitudes**;
los cuerpos `result`/`error` correspondientes entregados por SSE son
las **respuestas** -- incluyendo el caso donde la *tool* misma falló
(`isError: true`), que sigue siendo una respuesta JSON-RPC normal, no
un error a nivel de protocolo.

## 3. Conclusiones (punto 10 del enunciado)

### Características implementadas

Un servidor MCP local (stdio) y un servidor MCP con transporte remoto
(HTTP+SSE) para un caso de uso de laboratorio de inocuidad de
alimentos (LIMS), ambos implementando a mano JSON-RPC 2.0 y el
conjunto de métodos de MCP (`initialize`, `notifications/initialized`,
`tools/list`, `tools/call`) sin SDK; un chatbot host que habla con la
API de Messages de Anthropic directamente sobre HTTPS, mantiene
contexto de conversación entre turnos, orquesta ese servidor junto con
los servidores oficiales Filesystem y Git MCP, y registra cada
interacción MCP; un despliegue real y en vivo del servidor remoto
(`https://cc3067-lims-mcp.onrender.com`); y dos capturas de Wireshark
(local y contra ese despliegue en vivo) con una clasificación completa
de mensajes y análisis de capas OSI/TCP-IP de ambas.

### Dificultades encontradas

- **Google Cloud Run exigía una cuenta de facturación (tarjeta de
  crédito) antes de hacer cualquier cosa**, incluso para quedarse
  completamente dentro de su capa gratuita -- no hay forma de evitarlo
  del lado de GCP, y bloqueó el despliegue que nombraba la propuesta
  original. Resuelto desplegando en [Render](https://render.com) en su
  lugar: el enunciado permite explícitamente "Google Cloud, Cloudflare,
  etc.", la capa gratuita de servicios web de Render no pide tarjeta, y
  como `http_server.py` solo depende de variables de entorno simples
  (`HOST`/`PORT`) en vez de cualquier API específica de Cloud Run, el
  mismo `Dockerfile` exacto se desplegó en Render sin modificar nada --
  beneficio directo de haber mantenido la lógica de negocio del
  servidor desacoplada de su entorno de alojamiento desde el inicio. El
  único tradeoff real: la instancia gratis de Render se duerme tras 15
  minutos de inactividad (arranque en frío de 30-60s en la siguiente
  petición), contra los arranques en frío de Cloud Run, típicamente de
  menos de un segundo.
- **El servidor Git MCP publicado no tiene una tool `git_init`.**
  Verificado directamente contra la respuesta `tools/list` de `uvx
  mcp-server-git` y su código fuente instalado (`git_status`,
  `git_diff*`, `git_commit`, `git_add`, `git_reset`, `git_log`,
  `git_create_branch`, `git_checkout`, `git_show`, `git_branch` es la
  lista completa). El escenario demo del enunciado le pide
  explícitamente al chatbot "crear un repositorio", lo cual no es
  posible a través de una tool que ese servidor no expone. Resuelto
  haciendo que `chatbot/host.py` inicialice un repositorio vacío una
  vez al arrancar, con una llamada directa a `git init`, y dejando que
  el LLM haga todo lo demás (escribir el README, `git add`, `git
  commit`) a través de las tools MCP reales -- documentado como una
  solución alterna deliberada y transparente, no oculta.
- **`npx`/`uvx` no son directamente ejecutables desde
  `subprocess.Popen` en Windows.** Son shims `.cmd`/`.exe` de PATHEXT,
  y `Popen` sin `shell=True` falla al resolverlos con una búsqueda
  simple en `PATH` (`WinError 2`). Arreglado resolviendo el comando con
  `shutil.which()` primero en `stdio_client.py`, que es consciente de
  PATHEXT en Windows y no hace nada en POSIX -- encontrado y arreglado
  al correr realmente los servidores Filesystem y Git, no solo por
  inspección.
- **Las propias respuestas de Claude tumbaban la consola en Windows.**
  El codepage por defecto de la terminal de Windows (`cp1252`) no
  puede codificar Unicode arbitrario (checkmarks, emojis, algunos
  caracteres acentuados), y un `print()` simple del texto del modelo
  lanzaba `UnicodeEncodeError`, matando al chatbot a mitad de
  conversación la primera vez que una respuesta en vivo incluía uno.
  Esto solo aparece con salida real del modelo, no con ninguno de los
  fixtures de prueba escritos a mano usados antes -- detectado durante
  la corrida real de la demo en vivo. Arreglado reconfigurando
  `sys.stdout`/`sys.stderr` a UTF-8 (`errors="replace"`) al inicio del
  `main()` de `chatbot/host.py`.
- **La cuenta de Anthropic no tenía saldo utilizable al principio**,
  incluso después de crear una API key -- el crédito gratis prometido
  por el enunciado o no se aplicó o ya no es el default para cuentas
  nuevas, y la API devolvía un simple `400 invalid_request_error`
  ("credit balance is too low") en vez de un fallo de autenticación.
  Resuelto agregando una pequeña cantidad de crédito de facturación
  directamente; la API de Gemini de Google (genuinamente gratis sin
  tarjeta, verificado por separado) se evaluó como alternativa pero no
  se adoptó, ya que el código del chatbot existente está escrito
  específicamente contra la forma de la API de Messages de Anthropic y
  el costo real para el uso de este proyecto es de unos centavos.
- **Dos bugs de crash que solo aparecieron durante la corrida real de
  la demo en vivo contra el despliegue real, no contra ningún fixture
  de prueba escrito a mano:**
  1. Los clientes MCP de HTTP y de stdio definen cada uno su propia
     clase `MCPError` (mismo nombre, tipos distintos). El manejo de
     errores de llamadas a tools de `chatbot/host.py` solo importaba y
     capturaba la de stdio, así que un error del cliente HTTP -- que
     es exactamente lo que pasa cuando la instancia gratis de Render
     se recicla y olvida el `Mcp-Session-Id` del chatbot a mitad de
     conversación -- se propagaba sin capturar y mataba todo el
     proceso del chatbot en vez de reportarse como una llamada a tool
     fallida.
  2. El timeout de solicitud por defecto de
     `chatbot/mcp/http_client.py` (15s) era más corto que la ventana
     de arranque en frío de 30-60s que el propio
     `docs/deployment.md` documenta para la capa gratis de Render --
     una inconsistencia interna que hacía fallar el primer intento de
     conexión cada vez que el servidor se había dormido.

  Ambos se arreglaron la misma noche en que se encontraron, en vivo,
  horas antes de la presentación: el timeout se subió a un default
  configurable de 60s, `run_tool()` ahora captura los tipos de error de
  ambos clientes más un `except Exception` amplio final para que
  ninguna falla de una sola tool pueda volver a tumbar toda la sesión,
  y -- ya que la causa raíz es una característica real y recurrente de
  la capa gratis de Render, no un caso aislado -- un caso de sesión
  expirada específicamente dispara una reconexión automática con
  `initialize()` y un reintento antes de reportar el fallo, verificado
  corrompiendo deliberadamente una sesión en vivo y confirmando que el
  chatbot se recuperó de forma transparente.
- **Acceso concurrente a SQLite bajo `ThreadingHTTPServer`.** El
  transporte remoto atiende una petición por hilo, pero las tools de
  LIMS comparten una sola conexión SQLite; un único lock alrededor de
  la llamada compartida de despacho de protocolo en `http_server.py`
  serializa el acceso de forma segura sin complicar `tools.py` en sí.
- **Leer los bytes capturados reales, no asumir la forma del
  protocolo.** En vez de escribir el análisis de Wireshark solo a
  partir de la especificación, se tomó una captura local real y se
  inspeccionó con `tshark`, lo que reveló un detalle genuino y fácil de
  pasar por alto: el cliente HTTP de este proyecto abre una conexión
  TCP nueva por cada mensaje JSON-RPC en vez de reutilizar una -- una
  característica real de la implementación, algo que un escrito
  puramente teórico no habría detectado.

### Lecciones aprendidas

- Mantener los handlers de protocolo (`protocol.py`) y la lógica de
  negocio (`tools.py`, `database.py`) completamente agnósticos al
  transporte hizo que agregar un segundo transporte (HTTP + SSE) fuera
  un cambio genuinamente pequeño -- el servidor remoto es una capa
  nueva de framing/despacho, no una reimplementación, y está
  garantizado que se comporte idéntico al local porque llama a la
  misma tabla de despacho `METHOD_HANDLERS`.
- Diseñar el lado cliente de MCP (`chatbot/mcp/`) alrededor de una sola
  interfaz común (`initialize`, `call_tool`, `.tools`, `close`) hizo
  que el chatbot host nunca necesitara saber si un servidor dado es
  local (stdio) o remoto (HTTP) -- cambiar es un cambio de
  configuración de una línea en `servers_config.json`, que es
  exactamente lo que el enunciado le pide al chatbot que pueda hacer.
- Probar cada transporte directamente (JSON-RPC crudo sobre un pipe,
  `curl` contra el endpoint HTTP, una captura real con `tshark`) antes
  de conectar cualquier cosa al loop del LLM detectó bugs reales (el
  problema de `Popen` en Windows, la tool `git_init` faltante) que
  habrían sido mucho más difíciles de diagnosticar desde dentro de una
  conversación en vivo y no determinista con el LLM.
- Una captura contra un despliegue real revela cosas que una captura
  solo local simplemente no puede: la captura de loopback local nunca
  tiene una capa de enlace que inspeccionar y nunca toca TLS en
  absoluto, así que detalles como el framing Ethernet real, el
  enrutamiento real de internet a través del ISP/router, y el CDN
  delante de Render cerrando conexiones con `RST` en vez de un `FIN`
  elegante solo aparecieron una vez que el tráfico se capturó contra la
  URL en vivo -- confirmando que valió la pena desplegar de verdad en
  vez de tratar la captura de loopback como "suficientemente parecida".
