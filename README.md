# Simple Remote Control

Control the map and feature selection in QGIS 4 from another process on the same machine and under the same user account.

Open **Plugins → Simple Remote Control → Settings** to choose the address and whether to start automatically. By default, use **Start** in the toolbar or plugin menu. Use **Stop** before changing the address.

| Mode | macOS and Linux | Windows with Qt 6.11 or later |
| --- | --- | --- |
| **Qt** | Pass the name to `QLocalSocket.connectToServer()`. For a Unix socket client, use the name under QGIS's `QDir.tempPath()`. The default name is `qgis-remote-control`. | Pass the name to `QLocalSocket.connectToServer()`. The default name is `qgis-remote-control`. |
| **Absolute** | Connect to the configured Unix socket path. The default is `/tmp/qgis-remote-control.sock`. | Connect to the configured named pipe. The default is `\\.\pipe\qgis-remote-control`. |

If a crash leaves the Unix socket path occupied, choose another address or remove the socket file after confirming its server has stopped.

## Requests

Send UTF-8 JSON with a newline after each object. You can send multiple requests on one connection.

```jsonl
{"id":1,"method":"move","params":{"lat":48.8566,"lon":2.3522,"z":14}}
{"id":2,"method":"select","params":{"layer":"Places","expression":"strpos(\"name\", 'Café') > 0"}}
{"id":3,"method":"zoomToSelection","params":{"layer":0}}
```

- **move** accepts `lat` and `lon` in WGS 84, or `x`, `y` and `crs` such as `EPSG:2154`. Use a scale denominator such as `"scale":25000`, a Web Mercator zoom level `z` from 0 to 30, or neither for pan only. A blank map starts at zoom level 2 if you omit zoom.
- **select** replaces a vector layer's selection. **zoomToSelection** zooms to the selected features in a spatial vector or vector tile layer.
- **layer** is the first exact, case-sensitive Layers panel label or a zero-based position in the Layers tree. Hidden and nested layers count.

Replies use the same framing and echo the string or integer `id`. Success is `{"id":1,"ok":true}` and failure is `{"id":1,"ok":false,"error":"message"}`. Omit `id` to execute without a reply. Malformed lines and invalid IDs are discarded. A request larger than 1 MiB closes the connection.
