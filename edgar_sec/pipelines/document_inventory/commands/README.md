# document_inventory.commands — Command Implementations

## Purpose

Terminal subcommand implementations for the document inventory pipeline.

## Deliberate Gaps

- **No interactive prompts.** Prompts and menus are owned by `operator.py`.
- **JSON and terminal text only.** Output formatting stays in command handlers; prompts
  and menus are owned by `operator.py`.
