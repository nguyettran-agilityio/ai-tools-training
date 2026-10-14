"""Domain modules: user, book, category, borrowing, reservation.

Each module follows the same layering: routers -> services -> repositories
(interface + SQLite implementation) -> models, plus schemas (Pydantic DTOs).
"""
