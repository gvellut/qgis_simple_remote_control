# Simple Remote Control

Control the map and feature selection in QGIS 4 from another process under the same user account.

## Connection

Open **Plugins → Simple Remote Control → Settings** to choose the socket address. Enable **Restore server state on startup** to restore the last **Start** or **Stop** choice when QGIS opens. With the option off, use **Start** in the toolbar or plugin menu. Use **Stop** before changing the address.

| Mode | macOS and Linux | Windows |
| --- | --- | --- |
| **Qt** | Pass the name to `QLocalSocket.connectToServer()`. For a Unix socket client, use the name under QGIS's `QDir.tempPath()`. The default name is `qgis-remote-control`. | Pass the name to `QLocalSocket.connectToServer()`. The default name is `qgis-remote-control`. |
| **Absolute** | Connect to the configured Unix socket path. The default is `/tmp/qgis-remote-control.sock`. | Connect to the configured named pipe. The default is `\\.\pipe\qgis-remote-control`. |

*Note*: On Windows, Qt versions before 6.11 can accept named pipe connections from other machines when Windows file sharing and the pipe's access permissions allow it. Qt 6.11 and later reject remote clients. The QGIS 4.3 Windows build will use Qt 6.11.

If a crash leaves the Unix socket path occupied, choose another address or remove the socket file after confirming its server has stopped.

## Commands

### `move`

Center the map on a point, with optional zoom and a temporary marker.

| Argument | Type | Description |
| --- | --- | --- |
| `lat` | Number | WGS 84 latitude in degrees, from −90 to 90. Use with `lon`. |
| `lon` | Number | WGS 84 longitude in degrees, from −180 to 180. Use with `lat`. |
| `x` | Number | X coordinate in the supplied CRS. Use with `y` and `crs`. |
| `y` | Number | Y coordinate in the supplied CRS. Use with `x` and `crs`. |
| `crs` | String | Coordinate reference system of `x` and `y`, such as `EPSG:2154`. |
| `scale` | Number | Optional positive scale denominator. For example, `25000` sets the scale to 1:25,000. |
| `z` | Integer | Optional Web Mercator zoom level from 0 to 30. |
| `marker` | Boolean | Optional, defaults to `false`. Set to `true` to show a red marker above the map layers until the next pan or zoom. |

Supply either `lat` and `lon` or all three of `x`, `y`, and `crs`. Use at most one of `scale` and `z`. If you omit both, QGIS keeps the current scale or uses zoom level 2 for a blank map.

```jsonl
{"id":1,"method":"move","params":{"lat":48.8566,"lon":2.3522,"z":14,"marker":true}}
```

### `select`

Replace a vector layer’s selection with the features that match a QGIS expression.

| Argument | Type | Description |
| --- | --- | --- |
| `layer` | String or integer | Required. See [Layer identifiers](#layer-identifiers). |
| `expression` | String | Required. A nonempty QGIS expression evaluated against the layer. |

```jsonl
{"id":2,"method":"select","params":{"layer":"Places","expression":"strpos(\"name\", 'Café') > 0"}}
```

A successful reply includes `selectedCount`, the number of selected features, including zero.

```jsonl
{"id":2,"ok":true,"selectedCount":12}
```

### `zoomToSelection`

Zoom to the selected features in a spatial vector or vector tile layer. The layer must already have at least one selected feature.

| Argument | Type | Description |
| --- | --- | --- |
| `layer` | String or integer | Required. See [Layer identifiers](#layer-identifiers). |

```jsonl
{"id":3,"method":"zoomToSelection","params":{"layer":0}}
```

## Common notes

### Layer identifiers

- **String** matches the exact, case-sensitive label shown in the Layers panel. If several layers have the same label, the first match in tree order wins.
- **Integer** identifies a layer by its zero-based position in depth-first Layers tree order. Hidden layers and layers inside groups count.

### Request and reply format

- Send each request as one UTF-8 JSON object followed by a line feed (`\n`). You can send multiple requests on one connection.
- Set `method` to the command name and `params` to an object containing its arguments. Use a string or integer `id` to receive a reply. Omit `id` to execute the command without a reply.
- Replies use the same framing. Buffer incoming data until the line feed and match each reply to its request by `id`.
- The server discards invalid JSON, non-object messages, and requests with invalid IDs. A request larger than 1 MiB closes the connection.

| Result | Example reply |
| --- | --- |
| Success | `{"id":1,"ok":true}` |
| Error | `{"id":1,"ok":false,"error":"message"}` |
