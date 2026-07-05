#!/usr/bin/env python3
"""Simuliert die Gen2/3-RPC-API eines Shelly-Geräts zum Testen ohne echte Hardware.

Nutzung:
    python scripts/shelly_mock_server.py --port 8001 --type plug
    python scripts/shelly_mock_server.py --port 8002 --type 3em

Danach im Dashboard unter "Einstellungen" ein Gerät mit IP "localhost:8001"
(bzw. "localhost:8002") anlegen.
"""
import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

START_TIME = time.time()
ENERGY_WH_START = 12000.0  # willkürlicher Startzählerstand


def _fake_power(offset: float = 0.0, base: float = 150.0, amplitude: float = 80.0, period: float = 90.0) -> float:
    t = time.time() - START_TIME
    return max(0.0, base + amplitude * math.sin((t + offset) / period))


def _fake_energy(power_w: float) -> float:
    elapsed_h = (time.time() - START_TIME) / 3600.0
    return ENERGY_WH_START + power_w * elapsed_h


class Handler(BaseHTTPRequestHandler):
    device_type = "plug"

    def log_message(self, format, *args):
        pass

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if self.device_type == "plug" and path == "/rpc/Switch.GetStatus":
            power = _fake_power()
            self._send_json(
                {
                    "id": 0,
                    "apower": round(power, 1),
                    "voltage": 231.0,
                    "current": round(power / 231.0, 3),
                    "aenergy": {"total": round(_fake_energy(power), 1)},
                }
            )
            return

        if self.device_type == "3em" and path == "/rpc/EM.GetStatus":
            a, b, c = _fake_power(0), _fake_power(30), _fake_power(60)
            self._send_json(
                {
                    "id": 0,
                    "a_act_power": round(a, 1),
                    "b_act_power": round(b, 1),
                    "c_act_power": round(c, 1),
                    "total_act_power": round(a + b + c, 1),
                    "a_voltage": 230.1,
                    "b_voltage": 229.4,
                    "c_voltage": 230.8,
                    "a_current": round(a / 230.1, 3),
                    "b_current": round(b / 229.4, 3),
                    "c_current": round(c / 230.8, 3),
                    "a_pf": 0.87,
                    "b_pf": 0.91,
                    "c_pf": 0.79,
                    "a_freq": 50.0,
                    "b_freq": 50.0,
                    "c_freq": 50.0,
                }
            )
            return

        if self.device_type == "3em" and path == "/rpc/EMData.GetStatus":
            a, b, c = _fake_power(0), _fake_power(30), _fake_power(60)
            self._send_json(
                {
                    "id": 0,
                    "a_total_act_energy": round(_fake_energy(a), 1),
                    "b_total_act_energy": round(_fake_energy(b), 1),
                    "c_total_act_energy": round(_fake_energy(c), 1),
                    "total_act": round(_fake_energy(a) + _fake_energy(b) + _fake_energy(c), 1),
                }
            )
            return

        self.send_response(404)
        self.end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--type", choices=["plug", "3em"], default="plug")
    args = parser.parse_args()

    handler_cls = type("ConfiguredHandler", (Handler,), {"device_type": args.type})
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler_cls)
    print(f"Shelly-Mock ({args.type}) läuft auf Port {args.port} ...")
    server.serve_forever()


if __name__ == "__main__":
    main()
