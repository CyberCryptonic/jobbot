"""A local stand-in for a Greenhouse job-board application page, served on
127.0.0.1, so the Playwright driver can be tested end to end without touching
an employer. Mirrors the selectors the live page uses (inspected 2026-08-29):

  #application-form               the form
  input#first_name …              text inputs, id == API field name, aria-required
  input#resume[type=file]         hidden file input (class visually-hidden)
  input#question_X[role=combobox] react-select input; options render as
                                  [id^='react-select-question_X-option-'] and the
                                  chosen label shows in .select__single-value
  button[type=submit]             "Submit application"

Modes (query string on the job URL):
  ?challenge=after    an interactive challenge iframe renders after the click
  ?challenge=before   it renders on load
  ?login=1            a sign-in page instead of the form
  ?error=1            the submit fails and an alert renders
  ?hang=1             the submit never completes
  ?location=1         the standard candidate-location lookup renders (required;
                      absent from any probe/packet, exactly like the live board);
                      an empty value bounces the submit with an inline error and
                      no navigation — the live behavior of a large ATS board, 2026-09-01

Every POST to /api/apply is counted per job and its fields kept for asserts.
"""

import json
import re
import threading
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

QUESTIONS = [  # (name, type, label, options)
    ("first_name", "input_text", "First Name", None),
    ("last_name", "input_text", "Last Name", None),
    ("email", "input_text", "Email", None),
    ("country", "multi_value_single_select", "Country", ["Canada +1", "United Kingdom +44", "United States +1"]),
    ("phone", "input_text", "Phone", None),
    ("resume", "input_file", "Resume/CV", None),
    ("cover_letter", "input_file", "Cover Letter", None),
    ("question_1", "input_text", "LinkedIn Profile", None),
    ("question_2", "multi_value_single_select", "CLEARANCE ELIGIBILITY",
     ["Yes, I hold an active U.S. security clearance", "Yes, I am eligible for a U.S. security clearance", "No"]),
    ("question_3", "multi_value_single_select", "HISTORY WITH MERIDIAN", ["Yes", "No"]),
    ("question_4", "multi_value_single_select", "How did you hear about Meridian?",
     ["Google job search", "Indeed", "LinkedIn"]),
    ("question_5", "textarea", "Anything else?", None),
]

PAGE = """<!doctype html><html><head><title>Job Application for SOC Analyst at Fake Co</title>
<style>
.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.select__control{border:1px solid #888;padding:4px;min-height:32px;display:flex}
.select__single-value{margin-right:8px}
.select__menu{border:1px solid #888;background:#fff}
.select__option{padding:4px;cursor:pointer}
label{display:block;margin-top:10px;font-weight:bold}
#challenge{position:fixed;top:40px;left:40px;width:400px;height:500px;border:2px solid red;background:#fff;z-index:9}
</style></head><body>
<h1>SOC Analyst</h1>
<div id="challenge" style="display:none"><iframe title="recaptcha challenge expires in two minutes" src="/bframe" width="380" height="480"></iframe></div>
<form id="application-form" class="application--form">
%(fields)s
<button type="submit">Submit application</button>
</form>
<script>
const MODE = %(mode)s;
function makeSelect(name, options){
  const inp = document.getElementById(name);
  const wrap = inp.closest('.select__value-container');
  const cont = wrap.parentElement;
  let menu = null;
  function close(){ if(menu){menu.remove(); menu=null;} }
  function open(filter){
    close();
    menu = document.createElement('div'); menu.className='select__menu'; menu.setAttribute('role','listbox'); menu.id='react-select-'+name+'-listbox';
    options.forEach((o,i)=>{
      if(filter && !o.toLowerCase().includes(filter.toLowerCase())) return;
      const d=document.createElement('div'); d.className='select__option'; d.id='react-select-'+name+'-option-'+i;
      d.setAttribute('role','option'); d.textContent=o;
      d.addEventListener('mousedown', ev=>{ ev.preventDefault(); choose(o); });
      menu.appendChild(d);
    });
    cont.appendChild(menu);
  }
  function choose(o){
    let sv = wrap.querySelector('.select__single-value');
    if(!sv){ sv=document.createElement('div'); sv.className='select__single-value'; wrap.insertBefore(sv, wrap.firstChild); }
    // the live phone-country widget shows only the dial code once chosen
    sv.textContent = (name === 'country') ? (o.match(/\+\d+$/) || [o])[0] : o;
    inp.value=''; document.querySelector('input[name="'+name+'"][type=hidden]').value=o; close();
    if (MODE.wipe && name !== 'country') { const w=document.getElementById(MODE.wipe); if (w && !w.dataset.wiped) { w.value=''; w.dataset.wiped='1'; } }
  }
  inp.addEventListener('focus', ()=>open(''));
  inp.addEventListener('click', ()=>open(inp.value));
  inp.addEventListener('input', ()=>open(inp.value));
  inp.addEventListener('blur', ()=>setTimeout(close, 150));
}
%(selects)s
// the standard Location (City) lookup: options exist only after typing, the
// chosen label lands in .select__single-value (live recon 2026-09-01:
// input#candidate-location role=combobox -> #react-select-candidate-location-listbox)
function makeLookup(name){
  const inp = document.getElementById(name);
  const wrap = inp.closest('.select__value-container');
  const cont = wrap.parentElement;
  let menu = null;
  function close(){ if(menu){menu.remove(); menu=null;} }
  function expand(v){ return v.replace(/,\\s*NY$/i, ', New York').replace(/,\\s*ny\\b/i, ', New York'); }
  function open(v){
    close();
    if (!v || v.length < 3) return;
    const base = expand(v.trim());
    const opts = [base + ', United States', 'Town of ' + base + ', United States', base.split(',')[0] + ', Jamaica'];
    menu = document.createElement('div'); menu.className='select__menu-list'; menu.setAttribute('role','listbox');
    menu.id='react-select-'+name+'-listbox';
    opts.forEach((o,i)=>{
      const d=document.createElement('div'); d.className='select__option'; d.id='react-select-'+name+'-option-'+i;
      d.setAttribute('role','option'); d.textContent=o;
      d.addEventListener('mousedown', ev=>{ ev.preventDefault(); choose(o); });
      menu.appendChild(d);
    });
    cont.appendChild(menu);
  }
  function choose(o){
    let sv = wrap.querySelector('.select__single-value');
    if(!sv){ sv=document.createElement('div'); sv.className='select__single-value'; wrap.insertBefore(sv, wrap.firstChild); }
    sv.textContent = o;
    inp.value='';
    document.querySelector('input[name="'+name+'"][type=hidden]').value=o;
    const err = document.getElementById(name+'-error'); if (err) err.remove();
    close();
  }
  inp.addEventListener('input', ()=>setTimeout(()=>open(inp.value), 120));
  inp.addEventListener('blur', ()=>setTimeout(close, 150));
}
if (MODE.location) makeLookup('candidate-location');
if (MODE.challenge === 'before') document.getElementById('challenge').style.display='block';
document.getElementById('application-form').addEventListener('submit', async ev => {
  ev.preventDefault();
  if (MODE.location) {
    const hid = document.querySelector('input[name="candidate-location"][type=hidden]');
    if (!hid.value) {
      if (!document.getElementById('candidate-location-error')) {
        const e = document.createElement('div'); e.id='candidate-location-error';
        e.textContent = 'Please enter your location';
        document.getElementById('candidate-location').closest('.select__container').after(e);
      }
      return;                                  // no POST, no navigation — the live bounce
    }
  }
  if (MODE.challenge === 'after') { document.getElementById('challenge').style.display='block'; return; }
  if (MODE.hang) { return; }
  const fd = new FormData(ev.target);
  const r = await fetch('/api/apply?job=' + MODE.job, {method:'POST', body: fd});
  if (!r.ok) {
    const a=document.createElement('div'); a.setAttribute('role','alert'); a.textContent='There was an error submitting your application. Please try again.';
    document.body.prepend(a); return;
  }
  history.pushState({}, '', location.pathname + '/confirmation');
  document.body.innerHTML = '<h1>Thank you for applying</h1><p>We have received your application for SOC Analyst.</p>' + (MODE.assessment ? '<p>Next step: complete the HackerRank assessment within 5 days.</p>' : '');
});
</script></body></html>"""

LOGIN = """<!doctype html><html><head><title>Sign in</title></head><body><h1>Sign in to continue</h1>
<form id="login"><input id="username" type="text"><input id="password" type="password"><button type="submit">Sign in</button></form></body></html>"""


LOCATION_BLOCK = '''<label id="candidate-location-label" for="candidate-location">Location (City)*</label>
<div class="select__container"><div class="select__control"><div class="select__value-container">
<div class="select__input-container"><input class="select__input" id="candidate-location" role="combobox" type="text"
aria-autocomplete="list" aria-required="true" aria-labelledby="candidate-location-label"></div></div></div>
<input type="hidden" name="candidate-location" value=""></div>'''


def render(mode):
    parts, selects = [], []
    for name, typ, label, opts in QUESTIONS:
        req = ' aria-required="true"' if name in ("first_name", "last_name", "email", "question_2", "question_3", "question_4") else ""
        parts.append(f'<label id="{name}-label" for="{name}">{label}</label>')
        if typ == "input_text":
            parts.append(f'<input id="{name}" name="{name}" type="text" class="input"{req}>')
        elif typ == "textarea":
            parts.append(f'<textarea id="{name}" name="{name}" class="input"{req}></textarea>')
        elif typ == "input_file":
            parts.append(f'<input id="{name}" name="{name}" type="file" class="visually-hidden" accept=".pdf">'
                         f'<span id="{name}-filename"></span>'
                         f'<script>document.getElementById("{name}").addEventListener("change",e=>{{document.getElementById("{name}-filename").textContent=e.target.files[0]?e.target.files[0].name:""}})</script>')
        else:
            parts.append(f'<div class="select__container"><div class="select__control"><div class="select__value-container">'
                         f'<div class="select__input-container"><input class="select__input" id="{name}" role="combobox" type="text" '
                         f'aria-autocomplete="list" aria-labelledby="{name}-label"{req}></div></div></div>'
                         f'<input type="hidden" name="{name}" value=""></div>')
            selects.append(f"makeSelect({json.dumps(name)}, {json.dumps(opts)});")
    if mode.get("location"):
        parts.insert(5, LOCATION_BLOCK)        # between phone and resume, like the live form
    return PAGE % {"fields": "\n".join(parts), "selects": "\n".join(selects), "mode": json.dumps(mode)}


class FakeGreenhouse:
    """with FakeGreenhouse() as s: s.url('1') -> the job page; s.posts['1'] -> list of submissions."""

    def __init__(self):
        self.posts = {}
        self._srv = None
        self._thread = None

    def url(self, job="1", **mode):
        q = "&".join(f"{k}={v}" for k, v in mode.items())
        return f"http://127.0.0.1:{self.port}/fakeco/jobs/{job}" + (f"?{q}" if q else "")

    def __enter__(self):
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                m = re.match(r"^/fakeco/jobs/(\w+)(/confirmation)?$", u.path)
                if u.path == "/bframe":
                    return self._send(200, b"<html><body><p>Select all squares with a bus</p></body></html>")
                if not m:
                    return self._send(404, b"not found")
                if q.get("login"):
                    return self._send(200, LOGIN.encode())
                mode = {"job": m.group(1), "challenge": q.get("challenge"), "hang": bool(q.get("hang")),
                        "error": bool(q.get("error")), "assessment": bool(q.get("assessment")),
                        "wipe": q.get("wipe"), "location": bool(q.get("location"))}
                owner.modes = getattr(owner, "modes", {})
                owner.modes[m.group(1)] = mode
                return self._send(200, render(mode).encode())

            def do_POST(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                job = q.get("job", "?")
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n)
                msg = BytesParser(policy=email_policy).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw)
                fields = {}
                for part in msg.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    fn = part.get_filename()
                    fields[name] = {"filename": fn, "size": len(part.get_payload(decode=True) or b"")} if fn else part.get_content().strip()
                owner.posts.setdefault(job, []).append(fields)
                if owner.modes.get(job, {}).get("error"):
                    return self._send(500, b'{"error":"boom"}', "application/json")
                return self._send(200, b'{"ok":true}', "application/json")

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


if __name__ == "__main__":       # manual look: python tests/fake_greenhouse.py
    import time
    with FakeGreenhouse() as s:
        print(s.url("1"), s.url("2", challenge="after"))
        time.sleep(600)
