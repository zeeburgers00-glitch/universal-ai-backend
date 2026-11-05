"""Shared test isolation.

Quota counters and other runtime state live under ``UAI_DATA_ROOT``. Without
isolation, one test that simulates a 429 leaves the provider marked "exhausted"
for every later test in the session, which looks like a routing bug.

Nothing here touches the network: the directory is a per-session temp path.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_data_root():
    previous = os.environ.get("UAI_DATA_ROOT")
    path = Path(tempfile.mkdtemp(prefix="uai-tests-"))
    os.environ["UAI_DATA_ROOT"] = str(path)
    yield path
    if previous is None:
        os.environ.pop("UAI_DATA_ROOT", None)
    else:
        os.environ["UAI_DATA_ROOT"] = previous
