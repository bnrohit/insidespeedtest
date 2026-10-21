"""Test-only default, not a deployable admin credential."""
import os
os.environ.setdefault("ADMIN_PASSWORD", "TEST_ONLY_NEVER_USE_IN_PRODUCTION_123456789")
