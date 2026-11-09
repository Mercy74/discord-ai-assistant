
import os
from threading import Thread
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Discord AI Assistant is running!", 200


def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    server = Thread(target=run, daemon=True)
    server.start()
