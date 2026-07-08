import asyncio

from swebench.collect.utils import Repo


def _repo_without_network() -> Repo:
    repo = Repo.__new__(Repo)
    repo.owner = "owner"
    repo.name = "repo"
    repo.token = "token"
    return repo


def test_call_api_returns_sync_value():
    repo = _repo_without_network()

    def fake_api(**kwargs):
        return {"ok": True, **kwargs}

    assert repo.call_api(fake_api, number=1) == {"ok": True, "number": 1}


def test_call_api_resolves_awaitable_value():
    repo = _repo_without_network()

    async def fake_api(**kwargs):
        return {"ok": True, **kwargs}

    assert repo.call_api(fake_api, number=2) == {"ok": True, "number": 2}


def test_call_api_resolves_awaitable_value_inside_event_loop():
    repo = _repo_without_network()

    async def fake_api(**kwargs):
        return {"ok": True, **kwargs}

    async def run_inside_loop():
        return repo.call_api(fake_api, number=3)

    assert asyncio.run(run_inside_loop()) == {"ok": True, "number": 3}
