# Connectors — the Muse binding

The coding skills (`skills/coding_plan/`,
`skills/coding_implementation/`, `skills/coding_compaction/`)
work against external services through whatever connectors
the agent's harness provides. This file is the Muse-side
binding those skills point at; another harness substitutes
its own service integrations for the same roles.

- The GitHub connector for reading and working with
  repositories, files, issues and pull requests when the
  codebase lives on GitHub.
- Use `muse.connector_search` to find other connectors and
  `muse.skill_search` to find related skills.
- If nothing here fits, look on the web for a maintained API
  or MCP server and set it up with the harness's
  custom-connector setup skill, or build a custom connector.
