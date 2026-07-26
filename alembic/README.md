# Database migrations (Alembic)
#
# Requires DATABASE_URL in the environment or .env / .ENV.
#
#   python -m scripts.db current
#   python -m scripts.db history
#   python -m scripts.db revision -m "describe change" --autogenerate
#   python -m scripts.db upgrade head
#   python -m scripts.db downgrade -1
#   python -m scripts.db stamp head
#   python -m scripts.db check
#
# Or call Alembic directly:
#
#   python -m alembic upgrade head
#   python -m alembic revision --autogenerate -m "describe change"
