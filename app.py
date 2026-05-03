import json
import os
import sys
import time
from threading import Lock

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import queries as Q
from db import run

PORT = int(os.environ.get("PORT", "3000"))

DASHBOARD_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder=None)
CORS(app)

cache = {}
cache_lock = Lock()
TTL_MS = 5 * 60 * 1000


def pick_filters():
    out = {}
    for key in ("borough", "period", "class", "status"):
        v = request.args.get(key)
        if v and v != "All":
            out[key] = v
    return out


def cached_endpoint(key, builder):
    def handler():
        filters = pick_filters()
        ck = key + ":" + json.dumps(filters, sort_keys=True)
        now_ms = time.time() * 1000

        with cache_lock:
            hit = cache.get(ck)
        if hit and now_ms - hit["t"] < TTL_MS:
            resp = jsonify(hit["v"])
            resp.headers["X-Cache"] = "HIT"
            return resp

        try:
            t0 = time.time()
            v = builder(filters)
            with cache_lock:
                cache[ck] = {"v": v, "t": now_ms}
            print(f"[api] {ck}  computed in {int((time.time() - t0) * 1000)}ms")
            resp = jsonify(v)
            resp.headers["X-Cache"] = "MISS"
            return resp
        except Exception as e:
            print(f"[api] {ck} failed: {e}", file=sys.stderr)
            return jsonify({"error": str(e)}), 500

    handler.__name__ = f"endpoint_{key}"
    return handler


app.add_url_rule("/api/overview", view_func=cached_endpoint("overview", Q.overview))
app.add_url_rule("/api/parking",  view_func=cached_endpoint("parking",  Q.parking))
app.add_url_rule("/api/housing",  view_func=cached_endpoint("housing",  Q.housing))
app.add_url_rule("/api/dob",      view_func=cached_endpoint("dob",      Q.dob))
app.add_url_rule("/api/combined", view_func=cached_endpoint("combined", Q.combined))


@app.route("/api/health")
def health():
    try:
        rows = run("SELECT NOW() AS now")
        return jsonify({"ok": True, "now": rows[0]["now"].isoformat()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    with cache_lock:
        n = len(cache)
        cache.clear()
    return jsonify({"ok": True, "cleared": n})


@app.route("/")
def index():
    return send_from_directory(DASHBOARD_ROOT, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(DASHBOARD_ROOT, filename)


if __name__ == "__main__":
    print()
    print("  NYC Violations Dashboard")
    print("  ────────────────────────")
    print(f"  http://localhost:{PORT}")
    print()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
