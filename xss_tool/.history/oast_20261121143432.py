# oast.py
import threading

class SimpleOAST:
    def __init__(self, public_url: str, port: int = 8888):
        self.public_url = public_url
        self.port = port
        self.interactions: list[dict] = []
        self._started = False

    def start(self):
        if self._started:
            return
        from flask import Flask, request
        app = Flask("oast")
        app.logger.disabled = True

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def catch_all(path):
            self.interactions.append({
                "path": path, "args": dict(request.args),
                "ua": request.headers.get("User-Agent", ""),
                "ip": request.remote_addr,
            })
            return "", 204

        threading.Thread(
            target=lambda: app.run(host="0.0.0.0", port=self.port,
                                   debug=False, use_reloader=False),
            daemon=True,
        ).start()
        self._started = True

    def register(self) -> str:
        return self.public_url

    def poll(self) -> list[dict]:
        out = self.interactions[:]
        self.interactions.clear()
        return out