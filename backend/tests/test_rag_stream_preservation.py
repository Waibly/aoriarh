"""Preserve received bytes at stream buffer boundaries on transport failure."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.rag.agent import RAGAgent


@pytest.mark.parametrize("buffer_size", [1, 10])
@pytest.mark.parametrize("received", [0, 1, 2, 9, 10, 11, 12, 21])
async def test_transport_error_flushes_every_received_fragment_once(buffer_size, received):
    fragments = [f"  fragment {index}\n" for index in range(received)]
    failure = RuntimeError("simulated transport failure")

    async def response():
        for fragment in fragments:
            yield SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=SimpleNamespace(content=fragment))],
            )
        raise failure

    create = AsyncMock(return_value=response())
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    collected = []
    with pytest.raises(RuntimeError) as raised:
        async for fragment in agent.stream_generate("Question", [], buffer_size=buffer_size):
            collected.append(fragment)
    assert raised.value is failure
    assert "".join(collected) == "".join(fragments)
    create.assert_awaited_once()
