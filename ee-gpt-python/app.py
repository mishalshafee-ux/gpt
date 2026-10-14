import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename

load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "change-this-before-deploying")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "messages.json"
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
LOCK = threading.Lock()

ALLOWED = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".mp4", ".webm", ".mov"
}

admins = {
    os.environ.get("ADMIN1_USERNAME", "you"): os.environ.get("ADMIN1_PASSWORD", "change-this-password"),
    os.environ.get("ADMIN2_USERNAME", "friend"): os.environ.get("ADMIN2_PASSWORD", "change-this-password-too"),
}

def load_chats():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

chats = load_chats()

def save_chats():
    temp = DATA_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(chats, indent=2), encoding="utf-8")
    temp.replace(DATA_FILE)

def find_chat(chat_id):
    return next((chat for chat in chats if chat["id"] == chat_id), None)

def admin_required():
    if session.get("admin") not in admins:
        return jsonify(error="Please log in."), 401
    return None

def add_message(chat, text, files, sender, by=None):
    text = (text or "").strip()[:2000]
    attachments = []

    for file in files:
        if not file or not file.filename:
            continue
        original = secure_filename(file.filename)
        extension = Path(original).suffix.lower()
        if extension not in ALLOWED:
            continue
        saved_name = secrets.token_hex(16) + extension
        file.save(UPLOAD_DIR / saved_name)
        attachments.append({
            "name": original,
            "url": "/uploads/" + saved_name,
            "kind": "video" if extension in {".mp4", ".webm", ".mov"} else "image"
        })

    if not text and not attachments:
        return False

    message = {
        "text": text,
        "from": sender,
        "at": time.time(),
        "attachments": attachments
    }
    if by:
        message["by"] = by
    chat["messages"].append(message)
    return True

@app.get("/")
def home():
    return VISITOR_PAGE

@app.get("/admin")
def admin_page():
    return ADMIN_PAGE

@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    expected = admins.get(username)
    if expected is None or not hmac.compare_digest(password, expected):
        return jsonify(error="Username or password is incorrect."), 401
    session.clear()
    session["admin"] = username
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.post("/api/conversations")
def new_conversation():
    chat = {"id": secrets.token_urlsafe(18), "created": time.time(), "messages": []}
    with LOCK:
        chats.insert(0, chat)
        save_chats()
    return jsonify(chat)

@app.get("/api/conversations/<chat_id>")
def visitor_get_chat(chat_id):
    chat = find_chat(chat_id)
    if chat is None:
        return jsonify(error="Chat not found."), 404
    return jsonify(chat)

@app.post("/api/conversations/<chat_id>/messages")
def visitor_send(chat_id):
    chat = find_chat(chat_id)
    if chat is None:
        return jsonify(error="Chat not found."), 404
    with LOCK:
        if not add_message(chat, request.form.get("text", ""), request.files.getlist("files"), "visitor"):
            return jsonify(error="Write a message or attach an image/video."), 400
        save_chats()
    return jsonify(ok=True)

@app.get("/api/admin/conversations")
def admin_get_chats():
    error = admin_required()
    if error:
        return error
    return jsonify(chats)

@app.post("/api/admin/conversations/<chat_id>/messages")
def admin_send(chat_id):
    error = admin_required()
    if error:
        return error
    chat = find_chat(chat_id)
    if chat is None:
        return jsonify(error="Chat not found."), 404
    with LOCK:
        if not add_message(chat, request.form.get("text", ""), request.files.getlist("files"),
                           "human", session["admin"]):
            return jsonify(error="Write a reply or attach an image/video."), 400
        save_chats()
    return jsonify(ok=True)

VISITOR_PAGE = r"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ee.gpt</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#20231f;font:15px system-ui}
.layout{max-width:1100px;height:100vh;margin:auto;padding:18px;display:grid;grid-template-columns:240px 1fr;gap:16px}
aside,.main{background:#fff;border:1px solid #e8e7e2;border-radius:18px;padding:16px;min-height:0}
aside{display:flex;flex-direction:column}.brand{font-size:21px;font-weight:700;padding:6px 8px 18px}
button{border:0;background:#293a30;color:white;border-radius:11px;padding:11px 14px;font:inherit;cursor:pointer}
#new{width:100%;margin-bottom:14px}.history{overflow:auto}.chatitem{padding:11px;border-radius:10px;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chatitem:hover,.chatitem.active{background:#f0f0ec}
.main{display:flex;flex-direction:column}.head{padding:5px 6px 13px;border-bottom:1px solid #eee}
h1{font-size:19px;margin:0 0 4px}.muted{color:#777;font-size:13px}
#messages{flex:1;overflow:auto;padding:12px 6px}
.bubble{width:fit-content;max-width:85%;padding:12px 15px;border-radius:16px;background:#f0f0ec;margin:10px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.bubble.human{margin-left:auto;background:#dcebdc}
.bubble img,.bubble video{display:block;max-width:min(100%,480px);max-height:360px;border-radius:10px;margin-top:8px}
.composer{border-top:1px solid #eee;padding-top:12px}
form{display:flex;gap:8px;align-items:center}.text{min-width:0;flex:1;padding:13px;border:1px solid #ddd;border-radius:12px;font:inherit}
input[type=file]{max-width:180px;font-size:12px}.fine{font-size:12px;color:#777;margin:8px 2px 0}
@media(max-width:650px){.layout{grid-template-columns:1fr;height:100dvh;padding:8px;gap:8px}aside{max-height:150px}.brand{padding:0 4px 8px}.history{display:flex;gap:4px}.chatitem{min-width:120px}.main{min-height:0}input[type=file]{max-width:100px}}
</style></head><body><div class="layout">
<aside><div class="brand">ee.gpt</div><button id="new">＋ New chat</button><div class="history" id="history"></div></aside>
<section class="main"><div class="head"><h1 id="title">New chat</h1>
<div class="muted">Replies may be written by our support team.</div></div>
<div id="messages"></div><div class="composer">
<form id="form"><input class="text" id="text" maxlength="2000" placeholder="Message ee.gpt…">
<input type="file" id="files" accept="image/*,video/mp4,video/webm,video/quicktime" multiple>
<button>Send</button></form><div class="fine">Images and videos · 25 MB maximum per message</div>
</div></section></div><script>
let ids=JSON.parse(localStorage.eeChatIds||"[]"), current=localStorage.eeCurrentChat||"";
const box=document.querySelector("#messages");
function renderAttachment(a,parent){let el=document.createElement(a.kind==="video"?"video":"img");el.src=a.url;if(a.kind==="video")el.controls=true;parent.append(el)}
function showChat(c){current=c.id;localStorage.eeCurrentChat=current;document.querySelector("#title").textContent="Chat";
box.innerHTML="";for(const m of c.messages){let d=document.createElement("div");d.className="bubble "+(m.from==="human"?"human":"");if(m.text)d.append(document.createTextNode(m.text));for(const a of (m.attachments||[]))renderAttachment(a,d);box.append(d)}box.scrollTop=box.scrollHeight;drawHistory()}
async function openChat(id){let r=await fetch("/api/conversations/"+id);if(r.ok)showChat(await r.json())}
function drawHistory(){let h=document.querySelector("#history");h.innerHTML="";for(const id of ids){let d=document.createElement("div");d.className="chatitem"+(id===current?" active":"");d.textContent="Chat "+(ids.indexOf(id)+1);d.onclick=()=>openChat(id);h.append(d)}}
async function createChat(){let r=await fetch("/api/conversations",{method:"POST"}),c=await r.json();ids.unshift(c.id);ids=[...new Set(ids)];localStorage.eeChatIds=JSON.stringify(ids);showChat(c)}
async function refresh(){if(current)openChat(current)}
document.querySelector("#new").onclick=createChat;
document.querySelector("#form").onsubmit=async e=>{e.preventDefault();if(!current)await createChat();let data=new FormData();data.append("text",document.querySelector("#text").value);for(const f of document.querySelector("#files").files)data.append("files",f);
let r=await fetch("/api/conversations/"+current+"/messages",{method:"POST",body:data});if(r.ok){document.querySelector("#text").value="";document.querySelector("#files").value="";refresh()}else alert((await r.json()).error||"Could not send message.")};
drawHistory();if(current)openChat(current);else if(ids.length)openChat(ids[0]);else createChat();setInterval(refresh,3000);
</script></body></html>"""

ADMIN_PAGE = r"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ee.gpt admin</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#20231f;font:15px system-ui}
header{padding:16px 22px;background:white;display:flex;justify-content:space-between}
button{border:0;border-radius:10px;padding:11px 15px;background:#293a30;color:white;font:inherit;cursor:pointer}
input{padding:12px;border:1px solid #ddd;border-radius:10px;font:inherit}
#login{max-width:380px;margin:12vh auto;background:white;padding:24px;border-radius:18px}#login input{display:block;width:100%;margin:8px 0}
#layout{display:none;max-width:1100px;margin:22px auto;padding:0 14px;grid-template-columns:320px 1fr;gap:16px}
.panel{background:white;border:1px solid #e8e7e2;border-radius:16px;padding:16px;min-height:0}
.item{padding:12px;border-bottom:1px solid #eee;cursor:pointer}.item:hover{background:#f7f7f3}
#messages{height:55vh;overflow:auto}.bubble{padding:12px 14px;border-radius:15px;background:#f0f0ec;margin:10px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.human{background:#dcebdc;margin-left:auto;width:fit-content;max-width:85%}
.bubble img,.bubble video{display:block;max-width:min(100%,440px);max-height:340px;border-radius:9px;margin-top:8px}
.reply{display:flex;gap:8px;margin-top:10px}.reply input[type=text]{flex:1;min-width:0}
@media(max-width:650px){#layout{grid-template-columns:1fr}#messages{height:45vh}}
</style></head><body>
<header><b>ee.gpt · Admin inbox</b><button id="logout">Log out</button></header>
<section id="login"><h2>Admin login</h2><form id="loginform">
<input id="username" placeholder="Username" required><input id="password" type="password" placeholder="Password" required>
<button>Log in</button></form><p id="error"></p></section>
<div id="layout"><section class="panel"><h2>Chats</h2><div id="chats"></div></section>
<section class="panel"><h2 id="title">Choose a chat</h2><div id="messages"></div>
<form class="reply" id="reply"><input type="text" id="answer" placeholder="Write a reply…">
<input type="file" id="files" accept="image/*,video/mp4,video/webm,video/quicktime" multiple><button>Send</button></form></section></div>
<script>
let selected=null;
function attachment(a,d){let el=document.createElement(a.kind==="video"?"video":"img");el.src=a.url;if(a.kind==="video")el.controls=true;d.append(el)}
function show(c){document.querySelector("#title").textContent="Chat";let box=document.querySelector("#messages");box.innerHTML="";
for(let m of c.messages){let d=document.createElement("div");d.className="bubble "+(m.from==="human"?"human":"");if(m.text)d.append(document.createTextNode((m.from==="human"?(m.by||"Team")+": ":"Visitor: ")+m.text));for(const a of (m.attachments||[]))attachment(a,d);box.append(d)}box.scrollTop=box.scrollHeight}
async function load(){let r=await fetch("/api/admin/conversations");if(!r.ok)return;let all=await r.json(),list=document.querySelector("#chats");list.innerHTML="";
all.forEach((c,i)=>{let d=document.createElement("div");d.className="item";d.textContent="Chat "+(all.length-i)+" · "+(c.messages.at(-1)?.text||"Attachment").slice(0,45);d.onclick=()=>{selected=c.id;show(c)};list.append(d)});if(selected){let c=all.find(x=>x.id===selected);if(c)show(c)}}
document.querySelector("#loginform").onsubmit=async e=>{e.preventDefault();let r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:document.querySelector("#username").value,password:document.querySelector("#password").value})});
if(r.ok){document.querySelector("#login").style.display="none";document.querySelector("#layout").style.display="grid";load()}else document.querySelector("#error").textContent="Login failed."};
document.querySelector("#reply").onsubmit=async e=>{e.preventDefault();if(!selected)return alert("Choose a chat first.");let data=new FormData();data.append("text",document.querySelector("#answer").value);for(const f of document.querySelector("#files").files)data.append("files",f);
let r=await fetch("/api/admin/conversations/"+selected+"/messages",{method:"POST",body:data});if(r.ok){document.querySelector("#answer").value="";document.querySelector("#files").value="";load()}else alert((await r.json()).error||"Could not send reply.")};
document.querySelector("#logout").onclick=async()=>{await fetch("/api/logout",{method:"POST"});location.reload()};
setInterval(()=>{if(document.querySelector("#layout").style.display==="grid")load()},3000);
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "15570")))
