import asyncio
import threading
from unittest.mock import AsyncMock
import platform_api


def test_answer_persistence_runs_outside_event_loop(monkeypatch):
    async def scenario():
        loop_thread=threading.get_ident()
        request=AsyncMock()
        request.json.return_value={'selected_answer':'A'}
        def persist(sid,qid,received,data):
            assert threading.get_ident()!=loop_thread
            assert (sid,qid,data)==(1,2,{'selected_answer':'A'})
            return {'saved':True}
        monkeypatch.setattr(platform_api,'_save_answer_sync',persist)
        assert await platform_api.save_answer(1,2,request)=={'saved':True}
    asyncio.run(scenario())
