"""Permite executar via `python -m seguro_garantia`."""

from .cli import executar_cli

if __name__ == "__main__":
    raise SystemExit(executar_cli())
