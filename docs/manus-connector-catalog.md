# Manus Connector Catalog Reference

Verified 2026-09-15 from public Manus documentation.

## Sources

- [MCP Connectors](https://manus.im/docs/integrations/mcp-connectors) — categories and common connectors: Gmail, Google Calendar, Google Drive, Notion, HubSpot, Stripe, GitHub, Hugging Face, Slack.
- [Integrations](https://manus.im/docs/integrations/integrations) — MCP connectors, custom MCP servers, Zapier, Slack, Manus API, and data sources.
- [Manus API Connectors](https://open.manus.ai/docs/v2/connectors) — complete public connector table, UUIDs, connector selection semantics, and lifecycle rules.

## Catalog implementation

The frontend catalog mirrors the complete public connector table from the API documentation and stores each provider's stable UUID, category, auth mode, description, and readiness state. Direct Rawal connector implementations are marked **Ready**. Providers not yet backed by a verified local client are marked **MCP setup** rather than pretending that direct OAuth/token verification is already implemented.

This distinction is deliberate: a catalog entry is discoverable immediately, while connection execution must remain honest and permission-aware. The next extension point is a provider manifest registry that maps each catalog item to an OAuth schema, token test endpoint, MCP setup recipe, or custom connector adapter.

## Behavioral notes used in the UI

Manus documents explicit connector selection for tasks, multiple connectors per task, user/project defaults, follow-up override/clear/reuse semantics, OAuth authentication, and revocation from settings. These behaviors should be added to task composer state when connector-aware task execution is implemented.
