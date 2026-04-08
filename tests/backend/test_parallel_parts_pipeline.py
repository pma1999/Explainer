"""Tests for parallel parts pipeline configuration (see spec 2026-04-08)."""

from __future__ import annotations

import asyncio

import pytest


def test_max_concurrent_parts_matches_spec():
    import main

    assert main.MAX_CONCURRENT_PARTS == 5


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_workers():
    """Sanity-check: at most k tasks hold the critical section (same pattern as part_semaphore)."""
    k = 5
    sem = asyncio.Semaphore(k)
    active = 0
    max_active = 0

    async def worker() -> None:
        nonlocal active, max_active
        async with sem:
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*[worker() for _ in range(25)])
    assert max_active <= k
