"""ntfy push to the operator's phone (self-hosted ntfy, URL + topic in .env).

    import notify
    notify.push("Interview request", "Acme — SOC Analyst I: reply by Fri", priority=5,
                tags=["rotating_light"], click="http://localhost")

Returns True on HTTP 2xx, False otherwise; never raises, never logs the URL
or topic. The exception queue (interview / assessment / video / signature)
uses priority 5 ("urgent"); the nightly one-liner uses 3 ("default").
"""

import json
import urllib.error
import urllib.request

import db

TIMEOUT = 10


def _endpoint():
    return db.ENV["NTFY_URL"].rstrip("/") + "/" + db.ENV["NTFY_TOPIC"].strip("/")


def push(title, message, *, priority=3, tags=None, click=None):
    headers = {"Title": title.encode("ascii", "replace").decode(),
               "Priority": str(int(priority))}
    if tags:
        headers["Tags"] = ",".join(tags)
    if click:
        headers["Click"] = click
    req = urllib.request.Request(_endpoint(), data=message.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


if __name__ == "__main__":
    import sys
    ok = push("jobbot test", sys.argv[1] if len(sys.argv) > 1 else "ntfy path works", tags=["white_check_mark"])
    print("ntfy push:", "ok" if ok else "FAILED")
