"""
The old Rift Watch Fleet Doctrines address now just forwards to the doctrines'
new home inside Xar Reports. Every old link (doctrine pages, fits, downloads)
lands on the same page there, because doctrines kept their numbers.
"""
import os

from flask import Flask, redirect, request

app = Flask(__name__, static_folder=None)        # no files of its own: everything forwards
NEW = os.environ.get("NEW_DOCTRINE_SITE", "https://riftwatch-roam-report.onrender.com/doctrines").rstrip("/")
SITE = NEW.rsplit("/doctrines", 1)[0]


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def forward(path):
    q = ("?" + request.query_string.decode()) if request.query_string else ""
    if path.startswith(("sso/", "login")):                 # logging in now happens on the main site
        return redirect(f"{SITE}/sso/login?next=/doctrines/", 301)
    if path == "access":
        return redirect(f"{SITE}/editors", 301)
    return redirect(f"{NEW}/{path}{q}", 301)
