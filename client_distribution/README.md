# Contacter Client Distribution

This directory builds the B-side client and the optional A-side reference client. It deliberately contains no public Relay implementation, server configuration loader, session registry, public-port allocator, or server entry point.

Build and ship only this directory to B/A users:

```bash
python -m build client_distribution
```

Commands after installation:

```bash
contacter-client --config b-client.json
contacter-a-client --config a-client.json
```

The B client keeps its complete required behavior: B registration, authenticated heartbeat, NAT mapping maintenance, Relay packet handling, per-session local UDP bridge, local game replies, and session cleanup.
