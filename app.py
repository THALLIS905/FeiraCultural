import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Carrega o .env ANTES de qualquer leitura de variável de ambiente
load_dotenv()

from gemini_service import get_response  # noqa: E402 — importado após load_dotenv


app = Flask(__name__, static_folder="static")
CORS(app)


def _is_active() -> bool:
    """Lê SYSTEM_ACTIVE em tempo de requisição para garantir que o .env
    já foi processado — evita o bug onde o valor era lido no import time."""
    return os.environ.get("SYSTEM_ACTIVE", "false").strip().lower() == "true"


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/health")
def health():
    active = _is_active()
    return jsonify({"status": "ok", "active": active})


@app.route("/chat", methods=["POST"])
def chat():
    if not _is_active():
        return jsonify({
            "reply": (
                "🔧 Ops! O BYTE está em manutenção no momento. "
                "Nossa equipe DevFair está trabalhando duro para deixar tudo redondinho. "
                "Volte em breve! 😊"
            )
        })

    data = request.get_json(force=True, silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({
            "reply": "Ei, você me mandou uma mensagem vazia! 😅 Pode perguntar à vontade sobre a Feira Cultural TI."
        }), 400

    try:
        reply = get_response(user_message)
    except Exception as e:
        import sys
        print(f"[app] Erro inesperado ao obter resposta: {e}", file=sys.stderr)
        reply = "🤖 Tive uma pequena oscilação aqui nos circuitos, mas já estou pronto! Pode repetir sua pergunta?"

    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=True em desenvolvimento para ver erros; em produção o Gunicorn ignora este bloco
    debug = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
