---
name: implement-module
description: Implement a complete domain module (models, schemas, repository,
  service, router) following this project's layered architecture. Use when
  implementing or completing any module under app/modules/.
---

Implement the module specified in $ARGUMENTS, in this exact order,
following all rules in CLAUDE.md:

1. models.py — SQLModel model, matching the data model in CLAUDE.md
2. schemas.py — Pydantic DTOs: <Entity>Create, <Entity>Update, <Entity>Response
3. repositories.py — interface (Protocol/ABC) + SQLite implementation
4. services.py — business logic. NEVER import from fastapi.
   Raise domain exceptions from app/core/exceptions.py.
5. routers.py — thin layer: receive request → call service → return response
   in the standard format. Declare static routes before path-param routes.
6. Write unit tests for the service using a fake repository
7. Run `uv run pytest` and confirm all tests pass before finishing

After each step, give a short summary of what was done.
