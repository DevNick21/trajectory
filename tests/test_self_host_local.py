import pytest

from scripts.smoke_tests.self_host_local import run


@pytest.mark.asyncio
async def test_self_host_local_smoke_passes() -> None:
    result = await run()

    assert result.passed, result.failures
