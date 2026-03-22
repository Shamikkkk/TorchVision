from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active = [c for c in self._active if c is not ws]

    async def send(self, ws: WebSocket, data: dict) -> None:  # type: ignore[type-arg]
        await ws.send_json(data)

    async def broadcast(self, data: dict) -> None:  # type: ignore[type-arg]
        for ws in list(self._active):
            await ws.send_json(data)


manager = ConnectionManager()
