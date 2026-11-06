import asyncio
import json

from automater.portal_tokens import PortalTokens


def test_concurrent_sessions_use_each_token_only_once(tmp_path):
    tokens = PortalTokens(tmp_path / "approval.json")
    tokens.save("first")

    async def exercise():
        acquired = asyncio.Event()

        async def second():
            async with tokens.claim() as token:
                acquired.set()
                assert token == "second"
                tokens.save("third")

        async with tokens.claim() as token:
            assert token == "first"
            assert not tokens.path.exists()
            task = asyncio.create_task(second())
            await asyncio.sleep(0.1)
            assert not acquired.is_set()
            tokens.save("second")
        await asyncio.wait_for(task, 2)

    asyncio.run(exercise())
    assert json.loads(tokens.path.read_text())["restore_token"] == "third"


def test_invalid_tokens_are_discarded_and_forget_removes_only_approval(tmp_path):
    path = tmp_path / "approval.json"
    tokens = PortalTokens(path)
    preferences = tmp_path / "preferences.json"
    preferences.write_text("keep")
    path.write_text("invalid JSON")

    async def exercise():
        async with tokens.claim() as token:
            assert token is None
            tokens.save("new-token")
        await tokens.forget()

    asyncio.run(exercise())
    assert not path.exists()
    assert preferences.read_text() == "keep"
