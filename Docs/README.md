# AlignOS Documentation

Index of all AlignOS documentation. Start with the PRD for the product vision,
then SETUP + ROADMAP to build.

| Doc | Description |
| --- | --- |
| [prd.md](prd.md) | Full Product Requirements Document — vision, features, requirements, metrics, risks (all 32 sections). |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System components, the FastAPI↔MCP boundary, the two-layer memory model, and the three core runtime flows. |
| [DATA_MODEL.md](DATA_MODEL.md) | The 10 Neon Postgres tables, enums, relationships, indexes, and scoping rules. |
| [MCP_TOOLS.md](MCP_TOOLS.md) | The 8 MCP tool contracts, the 3 LLM prompt JSON contracts, and no-hallucination guardrails. |
| [API.md](API.md) | Backend HTTP endpoints, Slack mentions/commands/cards, scopes, and signature verification. |
| [SETUP.md](SETUP.md) | Local dev setup: prerequisites, repo layout, env vars, Slack app config. |
| [ROADMAP.md](ROADMAP.md) | The 7-phase build plan, MVP checklist, Final MVP definition, and demo script. |

## Suggested Reading Order

1. **[prd.md](prd.md)** — understand what AlignOS is and why.
2. **[ARCHITECTURE.md](ARCHITECTURE.md)** — understand how the pieces fit.
3. **[DATA_MODEL.md](DATA_MODEL.md)** + **[MCP_TOOLS.md](MCP_TOOLS.md)** +
   **[API.md](API.md)** — the implementation contracts.
4. **[SETUP.md](SETUP.md)** — get a dev environment running.
5. **[ROADMAP.md](ROADMAP.md)** — build it, phase by phase.

**Stack:** Python + FastAPI · `slack_sdk` / Slack Bolt · custom MCP server ·
Neon PostgreSQL · OpenRouter LLM.
