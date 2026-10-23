"""REST API routers, mounted at /api by app.main."""

from app.api.routers import books, knowledge, providers, queue, settings

routers = [providers.router, books.router, knowledge.router, queue.router, settings.router]
