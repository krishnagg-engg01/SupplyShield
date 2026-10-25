"""SupplyShield web app: Flask API + static dashboard.  Run: python app.py"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory

from supplyshield.config import ROOT
from supplyshield.service import AppService, ServiceError


def create_app(service: AppService | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    svc = service or AppService()
    app.config["svc"] = svc

    @app.errorhandler(ServiceError)
    def _svc_error(e: ServiceError):
        return jsonify({"error": e.message, "hint": e.hint, "details": e.details, "status": svc.status()}), e.status

    @app.errorhandler(Exception)
    def _unexpected(e):  # never leak stack traces / secrets to the browser
        app.logger.exception("Unhandled error")
        return jsonify({"error": "Unexpected server error. Check the terminal log.", "details": [type(e).__name__]}), 500

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/status")
    def status(): return jsonify(svc.status())

    @app.post("/api/connection/test")
    def test_conn(): return jsonify(svc.test_connection())

    @app.post("/api/mode")
    def mode():
        m = (request.get_json(silent=True) or {}).get("mode")
        if m == "demo": return jsonify(svc.use_demo())
        if m == "exasol": return jsonify(svc.use_exasol())
        raise ServiceError("mode must be 'demo' or 'exasol'.", 422)

    @app.post("/api/refresh")
    def refresh(): return jsonify(svc.refresh())

    @app.get("/api/dashboard")
    def dashboard(): return jsonify(svc.dashboard())

    @app.get("/api/entities")
    def entities(): return jsonify(svc.entities())

    @app.post("/api/simulate")
    def simulate(): return jsonify(svc.simulate(request.get_json(silent=True) or {}))

    @app.post("/api/runs/<run_id>/decision")
    def decision(run_id): return jsonify(svc.record_decision(run_id, request.get_json(silent=True) or {}))

    @app.get("/api/runs")
    def runs(): return jsonify(svc.runs())

    return app


if __name__ == "__main__":
    host, port = os.environ.get("SUPPLYSHIELD_HOST", "127.0.0.1"), int(os.environ.get("SUPPLYSHIELD_PORT", "5000"))
    print(f"SupplyShield running at http://{host}:{port}  (Ctrl+C to stop)")
    create_app().run(host=host, port=port, debug=False)
