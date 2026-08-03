# Deployment Area

Deployment is static and isolated.

```text
caddy/    reviewed NFL Edge site block and validation notes
scripts/  bounded bundle validation, transfer, activation, and rollback helpers
```

The VPS must not retain an NFL Python runtime, Streamlit service, raw training data, or model-training process.

All production changes must satisfy `docs/deployment_contract.md`.
