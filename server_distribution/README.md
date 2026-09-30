# Contacter Server Distribution

This directory builds the public Relay server. It contains server-only target configuration, session and registration state, public port listeners, routing rules, rate-limiting hooks, and Relay entry point.

Do not distribute this directory or its wheel to B/A clients.

```bash
python -m build server_distribution
```

After installation:

```bash
contacter-server --config relay.json
```
