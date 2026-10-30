"""Bound mutating request bodies before parsing or executing any endpoint."""
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 2_000_000
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes=MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        transfer = any(k.lower() == b"transfer-encoding" for k, _ in scope.get("headers", []))
        if len(lengths) > 1 or (lengths and transfer) or (lengths and not lengths[0].isdigit()):
            await JSONResponse({"detail": "Invalid request framing"}, status_code=400)(scope, receive, send)
            return
        if lengths and (len(lengths[0]) > 10 or int(lengths[0]) > self.max_bytes):
            await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        if lengths and len(body) != int(lengths[0]):
            await JSONResponse({"detail": "Invalid request framing"}, status_code=400)(scope, receive, send)
            return
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
