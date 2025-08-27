import json
import logging
import tornado.ioloop
import tornado.web
import tornado.websocket

from config import ORCHESTRATOR_PORT, configure_logging
from .pipeline import Orchestrator

logger = logging.getLogger(__name__)


class StreamHandler(tornado.websocket.WebSocketHandler):
    """Accepts PCM frames over WebSocket and forwards them to the orchestrator."""

    def initialize(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        self.flow_id: str | None = None

    async def open(self) -> None:  # pragma: no cover - Tornado callback
        self.buffer = bytearray()
        logger.info("WS connected from %s", self.request.remote_ip)

    async def on_message(self, message):  # pragma: no cover - Tornado callback
        if isinstance(message, bytes):
            logger.debug("[%s] WS recv %d bytes", self.flow_id, len(message))
            await self.orchestrator.feed_pcm(self.flow_id, message, self)
        else:
            msg = json.loads(message)
            logger.debug("WS control %s", msg)
            if msg.get("type") == "start":
                self.flow_id = msg.get("flowId")
                await self.orchestrator.start_flow(self.flow_id, self, msg)
            elif msg.get("type") == "flush":
                logger.info("[%s] WS flush", self.flow_id)
                await self.orchestrator.flush(self.flow_id)

    def on_close(self):  # pragma: no cover - Tornado callback
        if self.flow_id:
            logger.info("[%s] WS closed", self.flow_id)
            self.orchestrator.close_flow(self.flow_id)


def make_app() -> tornado.web.Application:
    orchestrator = Orchestrator()
    return tornado.web.Application([
        (r"/ws/stream", StreamHandler, dict(orchestrator=orchestrator)),
    ])


if __name__ == "__main__":  # pragma: no cover
    configure_logging()
    app = make_app()
    app.listen(ORCHESTRATOR_PORT)
    logger.info("Orchestrator server listening on port %s", ORCHESTRATOR_PORT)
    tornado.ioloop.IOLoop.current().start()
