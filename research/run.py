#!/usr/bin/env python3
"""Convenience entry point for running the TruePrice simulation platform."""
import os
import sys

# Ensure research directory is in PYTHONPATH
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from web.app import create_app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting TruePrice Simulation Platform at http://{host}:{port}")
    app = create_app()
    app.run(host=host, port=port, debug=False)
