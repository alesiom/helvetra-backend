"""
Shared test configuration and fixtures.
"""

import os

# Set test environment before importing app modules
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("APERTUS_API_KEY", "test-key")
os.environ.setdefault("APERTUS_API_BASE", "https://api.test.local")
os.environ.setdefault("APERTUS_MODEL", "test-model")
