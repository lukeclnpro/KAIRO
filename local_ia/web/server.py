"""Façade du serveur HTTP historique."""

from server import Handler, run_server

__all__ = ["Handler", "run_server"]


if __name__ == "__main__":
	import sys

	run_server(int(sys.argv[1]) if len(sys.argv) > 1 else 8080)