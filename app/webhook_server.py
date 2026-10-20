"""Part 4 student implementation."""

import json

import logging

import os

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        # Only messages/created events that carry a message ID.
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None

        data = event.get("data")
        if not isinstance(data, dict):
            return None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            return None

        # Ignore the bot's own messages before any API call.
        if data.get("personId") == self.bot_person_id:
            return None

        message = self.client.get_message(message_id)

        # Check the author of the fetched message too (prevents reply loops).
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        if not room_id:
            return None

        mentioned_people = message.get("mentionedPeople")
        files = message.get("files") or []

        try:
            if len(files) > 1:
                result = {"status": "error", "result": "multiple_attachments"}
            elif not files:
                result = self.processor(
                    mentioned_people, None, self.bot_person_id
                )
            else:
                content = self.client.download_file(files[0])
                # The temporary directory (and file) is removed even on failure.
                with TemporaryDirectory() as directory:
                    path = Path(directory) / "request.yaml"
                    path.write_bytes(content)
                    result = self.processor(
                        mentioned_people, path, self.bot_person_id
                    )
        except Exception:
            # Always answer the room, even when something unexpected fails.
            logger.exception("request processing failed")
            result = {"status": "error", "result": "backend_failed"}

        # Reply to the room that delivered this message.
        self.client.send_message(room_id, json.dumps(result))
        return result


def make_http_handler(submit_event):
    class WebhookRequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "result": "healthy"})
            else:
                self._send_json(404, {"status": "error", "result": "not_found"})

        def do_POST(self):
            if self.path != "/webhook":
                self._send_json(404, {"status": "error", "result": "not_found"})
                return

            invalid = {"status": "error", "result": "invalid_event"}

            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, invalid)
                return
            if length < 1 or length > MAX_BODY_BYTES:
                self._send_json(400, invalid)
                return

            try:
                event = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, invalid)
                return
            if not isinstance(event, dict):
                self._send_json(400, invalid)
                return

            submit_event(event)
            self._send_json(200, {"status": "ok", "result": "accepted"})

        def log_message(self, format, *args):
            logger.info("%s - %s", self.address_string(), format % args)

    return WebhookRequestHandler


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))

    client = WebexClient()

    # Resolve the bot's own person ID with its Bot Access Token.
    response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10,
    )
    response.raise_for_status()
    bot_person_id = response.json()["id"]

    handler = WebexEventHandler(client, bot_person_id)

    # One worker: router requests are processed one at a time.
    executor = ThreadPoolExecutor(max_workers=1)

    def log_failure(future):
        error = future.exception()
        if error is not None:
            logger.error("event processing failed: %r", error)

    def submit_event(event):
        executor.submit(handler.handle_event, event).add_done_callback(log_failure)

    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    logger.info("webhook listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()