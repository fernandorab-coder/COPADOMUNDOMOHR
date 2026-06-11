from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
import sqlite3
from urllib.parse import urlparse


ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "bolao.db")
ADMIN_PASSWORD = "9999"
PARTICIPANTS = ["Ana Paula", "Amilton", "Neto", "Diego", "Murilo", "Charles", "Fernando", "Cebola", "Guilherme"]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        create table if not exists official_scores (
            match_number integer primary key,
            a text not null,
            b text not null,
            pa text default '',
            pb text default '',
            locked integer not null default 1
        )
    """)
    conn.execute("""
        create table if not exists predictions (
            participant text not null,
            match_number integer not null,
            a text not null,
            b text not null,
            locked integer not null default 1,
            primary key (participant, match_number)
        )
    """)
    conn.execute("""
        create table if not exists extra_predictions (
            participant text primary key,
            champion text not null,
            brazil_phase text not null,
            brazil_goals text not null,
            locked integer not null default 1
        )
    """)
    conn.execute("""
        create table if not exists user_passwords (
            participant text primary key,
            password_hash text not null
        )
    """)
    conn.commit()
    return conn


def password_hash(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def state_payload():
    with db() as conn:
        scores = {}
        for row in conn.execute("select * from official_scores"):
            scores[str(row["match_number"])] = {
                "a": row["a"],
                "b": row["b"],
                "pa": row["pa"] or "",
                "pb": row["pb"] or "",
                "locked": bool(row["locked"]),
            }

        predictions = {}
        for row in conn.execute("select * from predictions"):
            predictions.setdefault(row["participant"], {})[str(row["match_number"])] = {
                "a": row["a"],
                "b": row["b"],
                "locked": bool(row["locked"]),
            }

        extras = {}
        for row in conn.execute("select * from extra_predictions"):
            extras[row["participant"]] = {
                "champion": row["champion"],
                "brazilPhase": row["brazil_phase"],
                "brazilGoals": row["brazil_goals"],
                "locked": bool(row["locked"]),
            }

        password_users = [
            row["participant"]
            for row in conn.execute("select participant from user_passwords")
        ]

    return {
        "scores": scores,
        "predictions": predictions,
        "extraPredictions": extras,
        "passwordUsers": password_users,
    }


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urlparse(path)
        if parsed.path in ("", "/"):
            return os.path.join(ROOT, "tabela_copa_2026.html")
        return os.path.join(ROOT, parsed.path.lstrip("/"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            json_response(self, 200, state_payload())
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = read_json(self)
            if parsed.path == "/api/login":
                self.api_login(payload)
            elif parsed.path == "/api/score":
                self.api_score(payload)
            elif parsed.path == "/api/prediction":
                self.api_prediction(payload)
            elif parsed.path == "/api/extras":
                self.api_extras(payload)
            else:
                json_response(self, 404, {"ok": False, "error": "Rota nao encontrada."})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def api_login(self, payload):
        name = str(payload.get("name", ""))
        password = str(payload.get("password", ""))
        confirmation = str(payload.get("confirmation", ""))

        if name == "Administrador":
            if password != ADMIN_PASSWORD:
                json_response(self, 403, {"ok": False, "error": "Senha incorreta."})
                return
            json_response(self, 200, {"ok": True, "role": "admin"})
            return

        if name not in PARTICIPANTS:
            json_response(self, 400, {"ok": False, "error": "Usuario invalido."})
            return

        with db() as conn:
            row = conn.execute(
                "select password_hash from user_passwords where participant = ?",
                (name,),
            ).fetchone()
            if row is None:
                if not password:
                    json_response(self, 400, {"ok": False, "error": "Digite a senha."})
                    return
                if password != confirmation:
                    json_response(self, 400, {"ok": False, "error": "As senhas nao conferem."})
                    return
                conn.execute(
                    "insert into user_passwords (participant, password_hash) values (?, ?)",
                    (name, password_hash(password)),
                )
                conn.commit()
                json_response(self, 200, {"ok": True, "role": "participant", "created": True})
                return

            if not hmac.compare_digest(row["password_hash"], password_hash(password)):
                json_response(self, 403, {"ok": False, "error": "Senha incorreta."})
                return

        json_response(self, 200, {"ok": True, "role": "participant"})

    def api_score(self, payload):
        number = int(payload["matchNumber"])
        with db() as conn:
            existing = conn.execute(
                "select locked from official_scores where match_number = ?",
                (number,),
            ).fetchone()
            if existing and existing["locked"]:
                json_response(self, 409, {"ok": False, "error": "Resultado oficial ja salvo."})
                return
            conn.execute(
                """
                insert into official_scores (match_number, a, b, pa, pb, locked)
                values (?, ?, ?, ?, ?, 1)
                on conflict(match_number) do update set
                    a = excluded.a,
                    b = excluded.b,
                    pa = excluded.pa,
                    pb = excluded.pb,
                    locked = 1
                """,
                (
                    number,
                    str(payload.get("a", "")),
                    str(payload.get("b", "")),
                    str(payload.get("pa", "")),
                    str(payload.get("pb", "")),
                ),
            )
            conn.commit()
        json_response(self, 200, {"ok": True, "state": state_payload()})

    def api_prediction(self, payload):
        participant = str(payload["participant"])
        number = int(payload["matchNumber"])
        with db() as conn:
            existing = conn.execute(
                "select locked from predictions where participant = ? and match_number = ?",
                (participant, number),
            ).fetchone()
            if existing and existing["locked"]:
                json_response(self, 409, {"ok": False, "error": "Palpite ja salvo."})
                return
            conn.execute(
                """
                insert into predictions (participant, match_number, a, b, locked)
                values (?, ?, ?, ?, 1)
                """,
                (participant, number, str(payload.get("a", "")), str(payload.get("b", ""))),
            )
            conn.commit()
        json_response(self, 200, {"ok": True, "state": state_payload()})

    def api_extras(self, payload):
        participant = str(payload["participant"])
        with db() as conn:
            existing = conn.execute(
                "select locked from extra_predictions where participant = ?",
                (participant,),
            ).fetchone()
            if existing and existing["locked"]:
                json_response(self, 409, {"ok": False, "error": "Apostas extras ja salvas."})
                return
            conn.execute(
                """
                insert into extra_predictions (participant, champion, brazil_phase, brazil_goals, locked)
                values (?, ?, ?, ?, 1)
                """,
                (
                    participant,
                    str(payload.get("champion", "")),
                    str(payload.get("brazilPhase", "")),
                    str(payload.get("brazilGoals", "")),
                ),
            )
            conn.commit()
        json_response(self, 200, {"ok": True, "state": state_payload()})


if __name__ == "__main__":
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("0.0.0.0", 3000), Handler)
    print("Bolao iniciado em http://localhost:3000")
    print("Banco de dados:", DB_PATH)
    server.serve_forever()
