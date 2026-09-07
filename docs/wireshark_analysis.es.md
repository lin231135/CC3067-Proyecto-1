# Análisis de Wireshark: chatbot &lt;-&gt; servidor MCP LIMS (HTTP + SSE)

> Traducción al español para referencia. La versión oficial es
> [`wireshark_analysis.md`](wireshark_analysis.md) (en inglés).

Este documento cumple los puntos #7 y #9 del enunciado: capturar toda
interacción entre el anfitrión y el servidor MCP, clasificar qué
mensajes JSON-RPC son de sincronización, solicitud, o respuesta, y
explicar qué sucede en cada capa OSI/TCP-IP.

## Dos capturas

Se tomaron dos capturas completas del mismo intercambio de 7 mensajes
(`initialize` -> `notifications/initialized` -> `tools/list` -> 4x
`tools/call`), y ambas se dejaron en el repositorio a propósito, como
comparación lado a lado:

1. **[`local_capture.pcapng`](wireshark/local_capture.pcapng)** -- el
   chatbot hablando con el servidor LIMS **corriendo localmente**
   (`python -m lims_mcp_server.http_server` en `127.0.0.1:8080`),
   capturado en el adaptador de loopback de Npcap en Windows. HTTP en
   texto plano, así que cada byte JSON-RPC es directamente visible --
   de esta se saca la evidencia detallada cuadro por cuadro de abajo.
2. **[`remote_capture.pcapng`](wireshark/remote_capture.pcapng)** -- el
   mismo intercambio, esta vez contra el **servidor remoto realmente
   desplegado** ("Análisis de la comunicación entre el servidor remoto
   y el cliente", según el enunciado):
   `https://cc3067-lims-mcp.onrender.com` (ver
   [`docs/deployment.es.md`](deployment.es.md) para saber por qué
   Render en vez de Cloud Run), capturada en la interfaz Wi-Fi real de
   la máquina. Esta es HTTPS real -- un frame Ethernet genuino,
   enrutamiento real, y un handshake TLS delante del mismo intercambio
   JSON-RPC, que la sección "Local vs. remoto" de abajo compara
   directamente contra la captura #1.

Ambas se produjeron con el mismo script exacto (un snippet simple de
Python usando `chatbot/mcp/http_client.py`), así que la única variable
entre ellas es texto plano local vs. TLS remoto.

## Cómo se produjo esta captura

```bash
# 1. Iniciar una captura en el adaptador de loopback, filtrada al puerto del servidor
dumpcap -i "Adapter for loopback traffic capture" -f "tcp port 8080" -w local_capture.pcapng

# 2. En otra terminal, correr el servidor LIMS
python -m lims_mcp_server.http_server

# 3. En una tercera terminal, ejercitarlo exactamente como lo hace el chatbot host:
#    initialize -> notifications/initialized -> tools/list -> cuatro tools/call
#    (list_pending_samples, get_sample_status exitoso, get_sample_status
#    error de no-encontrado, register_sample)
python -m chatbot.host   # o manejar chatbot/mcp/http_client.py directamente

# 4. Detener la captura, luego abrirla en Wireshark o inspeccionarla con tshark
```

En Windows, aparte de los problemas de PATH tipo `npx`/`uvx`, lo único
que vale la pena saber si repites esto: `urllib.request` de Python
(usado por `chatbot/mcp/http_client.py`) **no** reutiliza conexiones
TCP entre llamadas separadas a `urlopen()` -- cada mensaje JSON-RPC de
este proyecto abre una conexión TCP nueva (visible abajo como 7 valores
de `tcp.stream` separados para 7 mensajes, cada uno con su propio
handshake de 3 vías). Esta es una característica real y legítima del
tráfico de este proyecto que vale la pena reportar, no un artefacto de
la captura.

## Clasificación de mensajes

Cada uno de los 7 mensajes JSON-RPC enviados en esta captura, y a qué
categoría pertenece:

| # | `tcp.stream` | Método JSON-RPC | Categoría | HTTP | ¿Tiene `id`? |
|---|---|---|---|---|---|
| 1 | 0 | `initialize` (solicitud) | **Sincronización** (handshake de sesión/capacidades) | `POST /mcp` → `200`, `text/event-stream` | sí (`1`) |
| 2 | 1 | `notifications/initialized` | **Sincronización** (aviso de fin de handshake) | `POST /mcp` → `202 Accepted`, cuerpo vacío | no (notificación) |
| 3 | 2 | `tools/list` | **Solicitud** | `POST /mcp` → `200`, `text/event-stream` | sí (`2`) |
| 4 | 3 | `tools/call` (`list_pending_samples`) | **Solicitud** | `POST /mcp` → `200`, `text/event-stream` | sí (`3`) |
| 5 | 4 | `tools/call` (`get_sample_status`, encontrada) | **Solicitud** | `POST /mcp` → `200`, `text/event-stream` | sí (`4`) |
| 6 | 5 | `tools/call` (`get_sample_status`, no encontrada) | **Solicitud** | `POST /mcp` → `200`, `text/event-stream` | sí (`5`) |
| 7 | 6 | `tools/call` (`register_sample`) | **Solicitud** | `POST /mcp` → `200`, `text/event-stream` | sí (`6`) |

Y la mitad de **respuesta** de cada uno: cada frame SSE `event: message`
dentro de una respuesta HTTP `200` (streams 0, 2-6) es la **respuesta**
JSON-RPC a la solicitud de ese stream -- p. ej. la respuesta del stream
5 lleva `"result": {"content": [...], "isError": true}`, que es una
*respuesta* JSON-RPC normal aunque la llamada a la tool haya fallado
(ver [`docs/lims_mcp_server_spec.es.md`](lims_mcp_server_spec.es.md)
sobre errores de tool vs. errores de protocolo). El `202 Accepted` del
stream 1 **no** es una respuesta JSON-RPC en absoluto -- las
notificaciones nunca reciben una, según JSON-RPC 2.0; `202` es
puramente un acuse de recibo a nivel HTTP de que se recibió el flujo de
bytes.

**Por qué `initialize` + `notifications/initialized` cuentan como
"sincronización"**: según la especificación de MCP, estos dos mensajes
son la *fase de inicialización* -- el cliente y el servidor
intercambian versiones de protocolo y capacidades y acuerdan que están
listos para proceder, antes de que ocurra tráfico real de tools. Todo
lo que pasa después de ese punto (`tools/list`, `tools/call`) es
tráfico normal de solicitud/respuesta. Esto refleja, una capa más
arriba, exactamente lo que hace el propio handshake de tres vías de TCP
(`SYN` / `SYN, ACK` / `ACK`) a nivel de capa de transporte para cada una
de estas 7 conexiones -- ver la evidencia de paquetes abajo.

### Evidencia cruda: `initialize` (stream 0, sincronización)

```
Frame 1  127.0.0.1:52136 -> 127.0.0.1:8080  TCP [SYN] Seq=0
Frame 2  127.0.0.1:8080  -> 127.0.0.1:52136 TCP [SYN, ACK] Seq=0 Ack=1
Frame 3  127.0.0.1:52136 -> 127.0.0.1:8080  TCP [ACK] Seq=1 Ack=1

Frame 6  POST /mcp HTTP/1.1
         Content-Type: application/json
         Connection: close

         {"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                      "clientInfo": {"name": "cc3067-chatbot-host", "version": "1.0.0"}}}

Frame 10 HTTP/1.0 200 OK
         Content-Type: text/event-stream
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         event: message
         data: {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": false}},
                "serverInfo": {"name": "lims-food-analysis-mcp", "version": "1.0.0"}, ...}}
```

### Evidencia cruda: `notifications/initialized` (stream 1, sincronización, sin respuesta)

```
Frame 21 POST /mcp HTTP/1.1
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         {"jsonrpc": "2.0", "method": "notifications/initialized"}

Frame 23 HTTP/1.0 202 Accepted
         Content-Length: 0
```

### Evidencia cruda: caso de error en `tools/call` (stream 5, solicitud + respuesta)

```
Frame 79 POST /mcp HTTP/1.1
         Mcp-Session-Id: c76c891d05134ced8325fe4f99180a3a

         {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
          "params": {"name": "get_sample_status", "arguments": {"sample_code": "DOES-NOT-EXIST"}}}

Frame 83 HTTP/1.0 200 OK
         Content-Type: text/event-stream

         event: message
         data: {"jsonrpc": "2.0", "id": 5,
                "result": {"content": [{"type": "text", "text": "Sample 'DOES-NOT-EXIST' was not found."}],
                           "isError": true}}
```

Nota que esto es una **respuesta JSON-RPC** (tiene `"result"`) aunque la
*tool* haya fallado -- exactamente la decisión de diseño "errores de
tool vs. errores de protocolo" documentada en la especificación
principal.

## Resumen de la captura

```
Protocol Hierarchy Statistics (tshark -z io,phs)
frame  103 frames, 16396 bytes
  null (pseudo-header de loopback)
    ip
      tcp    103 frames, 16396 bytes
        http  14 frames (7 solicitudes + 7 respuestas)
          json   7 frames  (los cuerpos application/json de las solicitudes)
          media  6 frames  (los cuerpos text/event-stream de las respuestas;
                             la 7ma respuesta, el 202 a la notificación,
                             no tiene cuerpo)

TCP Conversations (tshark -z conv,tcp): 7 conexiones independientes,
una por mensaje JSON-RPC (52136-52142 <-> 8080), cada una con ~13-15
frames: SYN, SYN-ACK, ACK, PSH/ACK (solicitud), ACK, PSH/ACK
(respuesta), ACK, y luego un intercambio FIN/ACK en ambas direcciones
para cerrar.
```

## Explicación de capas OSI / TCP-IP

Basado directamente en los paquetes de arriba (el frame 1, expandido
con `tshark -V`, es el ejemplo trabajado):

- **Capa de enlace.** La captura **local** se tomó en el adaptador de
  loopback de Npcap, así que Wireshark muestra un pseudo-header
  **Null/Loopback** (`Encapsulation type: NULL/Loopback`, "Protocols in
  frame: `null:ip:tcp`") en vez de un frame real de capa de enlace -- el
  tráfico de loopback nunca sale realmente por un cable ni por el aire,
  así que no hay header Ethernet/802.11, ni direcciones MAC, ni ARP. La
  captura **remota**, tomada en el adaptador Wi-Fi real, muestra
  exactamente lo que esa captura local no podía: un frame **Ethernet
  II** genuino, `Src: AzureWaveTec_b1:8f:d7 (70:66:55:b1:8f:d7)` (la NIC
  Wi-Fi de la laptop), `Dst: BaoanGaokeEl_28:a2:d5
  (00:16:78:28:a2:d5)` (la MAC del router de casa) -- confirmado
  directamente con `tshark -V` en el frame 1 de `remote_capture.pcapng`.
- **Capa de red (IP).** La captura local es `127.0.0.1 -> 127.0.0.1`
  (mismo host, sin enrutamiento real). La captura remota muestra
  enrutamiento IPv4 real: `192.168.11.230` (la dirección LAN privada de
  la laptop) -> `216.24.57.7` (el borde de Render, en realidad una
  dirección de Cloudflare para `cc3067-lims-mcp.onrender.com` --
  confirmado con `nslookup`, que resolvió el hostname a través de
  `*.cdn.cloudflare.net`). La dirección de origen privada es traducida
  (NAT) por el router de casa antes de llegar al internet público, algo
  que Wireshark del lado del cliente no puede mostrar directamente (esa
  traducción ocurre en el router, después de este punto de captura).
- **Capa de transporte (TCP).** Ambas capturas muestran el mismo patrón
  subyacente: **7 conexiones TCP independientes**, una por mensaje
  JSON-RPC (las llamadas `urllib` de `chatbot/mcp/http_client.py` no
  reutilizan conexiones), cada una con su propio handshake de 3 vías
  (`SYN` -> `SYN, ACK` -> `ACK`). `tshark -z conv,tcp` en la captura
  remota confirma exactamente 7 conversaciones a `216.24.57.7:443` (más
  una atípica de 2 frames a una segunda IP de borde de Cloudflare,
  `216.24.57.15`, de una conexión que fue redirigida a otro nodo de
  borde). La única diferencia estructural: varias de las conexiones
  remotas terminan con un **`RST`** de TCP en vez de un cierre limpio
  `FIN`/`FIN,ACK` (visible en `remote_capture.pcapng`, p. ej. frame 17)
  -- consistente con que el CDN/proxy delante de Render cierra de forma
  más agresiva las conexiones `Connection: close` de HTTP/1.0 de corta
  duración, en vez de esperar un cierre elegante de 4 vías, algo que el
  `http.server` local de Python nunca hace. TCP es lo que le da al
  intercambio JSON-RPC entrega confiable y en orden sobre la capa IP
  sin conexión de abajo, en ambos casos -- esto también es *por qué*
  HTTP (y por lo tanto el transporte Streamable HTTP de MCP) está
  construido sobre TCP y no UDP: los mensajes JSON-RPC deben llegar
  completos y en orden, o el parseo de JSON en
  `http_server.py`/`http_client.py` se rompería.
- **Capa de aplicación (HTTP + SSE + JSON-RPC, más TLS en el camino
  remoto).** Localmente, son tres framings anidados: **HTTP** (`POST
  /mcp`, headers, códigos de estado) lleva **SSE** (`Content-Type:
  text/event-stream`, `event: message` / `data: ...`) que lleva
  **JSON-RPC 2.0** (`{"jsonrpc": "2.0", "id": ...,
  "method"/"result": ...}`) como el payload de `data:` -- todo legible
  en texto plano, como se muestra en la evidencia cruda de arriba. En
  el camino remoto, `tshark -z io,phs` en `remote_capture.pcapng`
  muestra una capa **`tls`** ubicada entre TCP y donde estaría HTTP (59
  de 130 frames, 40444 de 47167 bytes): un **handshake TLS** real
  (`ClientHello` -> `ServerHello` -> certificado ->
  `ChangeCipherSpec`, tipos de contenido de record `22`/`20` en la
  captura) ocurre primero, y cada byte JSON-RPC después de eso viaja
  dentro de records **TLS Application Data** encriptados en vez de un
  cuerpo HTTP en texto plano -- Wireshark no puede mostrar la línea
  `POST /mcp` ni el JSON en sí para esta captura, solo que *alguna*
  solicitud salió y *alguna* respuesta volvió, con qué tamaño y en qué
  momento. El header `Mcp-Session-Id` es estado específico de MCP a
  nivel de capa de aplicación, sobre HTTP, correlacionando solicitudes
  por lo demás sin estado en una sesión MCP lógica -- solo que en el
  camino remoto está adicionalmente encriptado.

## Local vs. remoto, lado a lado

| | Local (`local_capture.pcapng`) | Remoto (`remote_capture.pcapng`) |
|---|---|---|
| Destino | `127.0.0.1:8080` | `cc3067-lims-mcp.onrender.com` (`216.24.57.7:443`) |
| Interfaz de captura | Adaptador de loopback de Npcap | Wi-Fi (NIC real) |
| Capa de enlace | Pseudo-header Null/Loopback | Ethernet II real, direcciones MAC reales |
| Capa de red | `127.0.0.1 -> 127.0.0.1` | `192.168.11.230 -> 216.24.57.7`, enrutamiento real de internet |
| Seguridad | Ninguna (texto plano) | TLS (`ClientHello`/`ServerHello`, Application Data encriptado) |
| ¿JSON-RPC visible en Wireshark? | Sí, directamente | No -- encriptado; solo se ven tamaño/tiempo/dirección sin desencriptar la sesión |
| Conexiones TCP | 7 (una por mensaje), cierres `FIN` limpios | 7 (una por mensaje) + 1 atípica, algunas cerradas con `RST` en vez de `FIN` |
| Total de frames / bytes | 103 frames / 16,396 bytes | 130 frames / 47,167 bytes (overhead de TLS) |

La clasificación de sincronización/solicitud/respuesta de la sección de
arriba es idéntica en ambas -- es una propiedad de la secuencia de
mensajes JSON-RPC/MCP, no del envoltorio de seguridad del transporte.
Lo que cambia entre ellas es exactamente lo que se esperaría al agregar
TLS y un salto de red real: un handshake antes que cualquier otra cosa,
más bytes en el cable, y el payload en sí volviéndose opaco para un
observador pasivo -- que es, de hecho, todo el punto de desplegar esto
sobre HTTPS en vez de HTTP plano.
