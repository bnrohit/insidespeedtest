"""Test-only environment so pytest can import the module-level ASGI app."""
import os
os.environ.setdefault("ADMIN_PASSWORD", "TEST_ONLY_NEVER_USE_IN_PRODUCTION_123456789")
