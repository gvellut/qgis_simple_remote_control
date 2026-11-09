# Writing a client

- Connect with `QLocalSocket` using the configured name or address. On macOS/Linux a native Unix socket client can also use the absolute address. In Qt mode the path is QGIS's `QDir.tempPath()` plus the name. Windows uses a local named pipe.
- Send one UTF-8 JSON object followed by LF. Use `{"id":1,"method":"select","params":{"layer":0,"expression":"strpos(\"name\", 'Café') > 0"}}` as a template. Buffer reads until LF and match replies by `id`. Omit `id` for a command with no reply.
- `move` takes `lat/lon` or `x/y/crs`, with optional `scale` (denominator) or `z` (Web Mercator zoom). `select` takes `layer/expression` and replaces the selection. `zoomToSelection` takes `layer`.
- A layer index starts at zero in depth-first Layers tree order, including hidden and nested layers. A label is an exact case-sensitive match, with the first match winning.

See [README.md](README.md) for the full request examples and default addresses.
