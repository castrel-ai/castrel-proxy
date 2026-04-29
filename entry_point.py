#!/usr/bin/env python
"""Entry point for PyInstaller - uses absolute imports."""
import os
import sys

if getattr(sys, "frozen", False):
    import certifi

    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from castrel_proxy.cli.commands import run

if __name__ == "__main__":
    run()
