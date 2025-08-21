"""Minimal gRPC stub for ASR service."""


class _FakeStream:
    async def write(self, frame):
        pass

    async def done_writing(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class RecognizeStub:
    def __init__(self, channel):
        self.channel = channel

    def Stream(self):
        return _FakeStream()
