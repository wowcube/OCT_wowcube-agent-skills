"""Self-contained HTML review page for the artist / art lead.

One file (images inlined), opens in any browser, no server: anchors and
palette on top, then every set and asset with the raw model output, the final
sprite at x4 (nearest), QA + style verdicts and the prompt used. Each asset
has OK / Fix buttons and a note field; "Copy feedback" puts a JSON blob on
the clipboard that the artist pastes back into the chat, where it becomes
fixes.json entries for the next regeneration round.
"""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image

CSS = """
:root{--bg:#16130f;--panel:#221d17;--line:#3a3128;--text:#ece3d6;--dim:#a99c8a;--ok:#5fbf6a;--warn:#e0b44c;--fail:#e0604c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line)}h1{margin:0 0 4px;font-size:20px}h2{font-size:16px;margin:28px 24px 8px}
.dim{color:var(--dim)}.row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.anchors img{height:160px;border:1px solid var(--line);border-radius:6px;image-rendering:pixelated}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin:8px 24px;display:grid;
 grid-template-columns:200px 220px 1fr;gap:14px}
.card img{max-width:100%;border-radius:6px;background:#463428;image-rendering:pixelated}
.name{font-weight:600;font-size:15px}.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;margin:2px 4px 2px 0}
.PASS{background:#1f3a22;color:var(--ok)}.WARN{background:#3d3218;color:var(--warn)}.FAIL{background:#40201b;color:var(--fail)}
.UNCHECKED,.STALE{background:#2a2a35;color:#b8b8d0}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
.px{border-radius:6px;background:#463428;display:flex;gap:8px;align-items:flex-end;padding:6px}
body.bg-light .px{background:#e8e2d8}body.bg-dark .px{background:#141210}
body.bg-checker .px{background:#888;background-image:linear-gradient(45deg,#bbb 25%,transparent 25%,transparent 75%,#bbb 75%),linear-gradient(45deg,#bbb 25%,transparent 25%,transparent 75%,#bbb 75%);background-size:16px 16px;background-position:0 0,8px 8px}
.gifs{display:flex;gap:12px;flex-wrap:wrap;padding:0 24px}.gifs figure{margin:0}.gifs img{image-rendering:pixelated;border-radius:6px}
details{margin-top:6px}summary{cursor:pointer;color:var(--dim)}pre{white-space:pre-wrap;font-size:12px;color:var(--dim);margin:6px 0}
ul{margin:4px 0 0 18px;padding:0}li{font-size:12px}.fb{margin-top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{background:#2f281f;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:4px 10px;cursor:pointer}
button.on.okb{background:#1f3a22;border-color:var(--ok)}button.on.fixb{background:#40201b;border-color:var(--fail)}
textarea{width:100%;min-height:38px;background:#1b1712;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px}
.sheet img{max-width:calc(100% - 48px);margin:0 24px;border-radius:8px}
footer{position:sticky;bottom:0;background:#0f0d0aee;border-top:1px solid var(--line);padding:10px 24px;display:flex;gap:12px;align-items:center}
@media (max-width:760px){.card{grid-template-columns:1fr}}
"""

JS = """
const fb=Object.create(null);
const KEY='artreview:'+PROJECT;
try{const s=JSON.parse(localStorage.getItem(KEY)||'{}');for(const k in s){fb[k]=s[k]}}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(fb))}catch(e){}}
function restore(){document.querySelectorAll('.fb').forEach(r=>{const n=r.dataset.n;if(!fb[n])return;
 if(fb[n].status){const b=r.querySelector(fb[n].status==='ok'?'.okb':'.fixb');if(b)b.classList.add('on')}
 const t=r.parentElement.querySelector('textarea');if(t&&fb[n].note)t.value=fb[n].note});upd()}
function mark(n,s,b){fb[n]=fb[n]||{};fb[n].status=s;b.parentElement.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');save();upd()}
function note(n,t){fb[n]=fb[n]||{};fb[n].note=t;save();upd()}
function upd(){const k=Object.keys(fb);const fix=k.filter(x=>fb[x].status==='fix').length,ok=k.filter(x=>fb[x].status==='ok').length,
 loose=k.filter(x=>!fb[x].status&&fb[x].note).length;
 document.getElementById('cnt').textContent=fix+' to fix, '+ok+' approved, '+(TOTAL-fix-ok)+' not reviewed'+(loose?' - '+loose+' note(s) without OK/Fix will be ignored':'')}
function payload(){return JSON.stringify({project:PROJECT,review:fb},null,1)}
function download(t){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([t],{type:'application/json'}));a.download=PROJECT+'_feedback.json';a.click()}
function copyFb(){const t=payload();try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(()=>{document.getElementById('cnt').textContent='copied - paste it into the chat'},()=>download(t));return}}catch(e){}download(t)}
function bg(c){document.body.classList.remove('bg-light','bg-dark','bg-checker');if(c)document.body.classList.add(c)}
window.addEventListener('DOMContentLoaded',restore);
"""


def _b64(img: Image.Image, max_side: int | None = None, scale: int | None = None) -> str:
    img = img.convert("RGBA")
    if scale:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build(project, final_dir: Path, raw_dir: Path, report: dict, prompts: dict, style_dir: Path) -> Path:
    ws = project.workspace
    esc = html.escape
    results = report.get("assets", {}) if report else {}
    rj = ws / "qa" / "report.json"
    report_time = rj.stat().st_mtime if rj.exists() else 0.0
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>{esc(project.name)} art review</title><style>{CSS}</style></head><body>"]
    n_fail = sum(1 for r in results.values() if any(not c["ok"] and c["hard"] for c in r.get("checks", [])))
    parts.append(f"<header><h1>{esc(project.name)} - art review</h1><div class='dim'>{len(project.assets)} assets, "
                 f"{n_fail} with failed checks. Mark each asset OK or Fix, add a note, then Copy feedback "
                 f"(marks are kept in this browser until you send them).</div>"
                 "<div class='tools'><span class='dim'>Background:</span><button onclick=\"bg('')\">brown</button>"
                 "<button onclick=\"bg('bg-dark')\">dark</button><button onclick=\"bg('bg-light')\">light</button>"
                 "<button onclick=\"bg('bg-checker')\">checker</button></div></header>")
    if project.anchors:
        parts.append("<h2>Style anchors</h2><div class='row anchors' style='padding:0 24px'>")
        for p in project.anchors:
            if p.exists():
                parts.append(f"<img src='{_b64(Image.open(p), 320)}' title='{esc(p.name)}'>")
        pal = style_dir / "palette.png"
        if pal.exists():
            parts.append(f"<div><div class='dim'>Palette (from the anchors)</div><img src='{_b64(Image.open(pal))}' style='height:48px'></div>")
        parts.append("</div>")
    sheet = ws / "qa" / "sets.png"
    if sheet.exists():
        parts.append(f"<h2>Sets: frames and onion skin</h2><div class='sheet'><img src='{_b64(Image.open(sheet), 1600)}'></div>")
    gifs = sorted((ws / "qa").glob("*.gif"))
    if gifs:
        parts.append("<h2>Animations (flipbooks)</h2><div class='gifs'>")
        for g in gifs:
            data = base64.b64encode(g.read_bytes()).decode()
            parts.append(f"<figure><img src='data:image/gif;base64,{data}'><figcaption class='dim'>{esc(g.stem)}</figcaption></figure>")
        parts.append("</div>")
    order = []
    for a in project.assets:
        order.append((a.set or "~", a))
    order.sort(key=lambda t: (t[0], project.assets.index(t[1])))
    cur = None
    for sname, a in order:
        if sname != cur:
            cur = sname
            parts.append(f"<h2>{esc('Set: ' + sname if sname != '~' else 'Single assets')}</h2>")
        r = results.get(a.name, {})
        checks = r.get("checks", [])
        fin = final_dir / f"{a.name}.png"
        if not checks:
            verdict = "UNCHECKED"
        elif fin.exists() and fin.stat().st_mtime > report_time + 1:
            verdict = "STALE"          # the image changed after the last qa run
        else:
            verdict = "FAIL" if any(not c["ok"] and c["hard"] for c in checks) else ("WARN" if any(not c["ok"] for c in checks) else "PASS")
        st = r.get("style")
        raw = raw_dir / f"{a.name}.png"
        k = max(2, min(8, 200 // max(a.size)))
        raw_img = f"<img src='{_b64(Image.open(raw), 200)}' title='raw model output'>" if raw.exists() else "<div class='dim'>no raw image</div>"
        fin_img = (f"<div class='px'><img src='{_b64(Image.open(fin))}' title='1x'><img src='{_b64(Image.open(fin), scale=k)}' "
                   f"title='x{k}'></div>") if fin.exists() else "<div class='dim'>not processed</div>"
        items = "".join(f"<li class='{'dim' if c['ok'] else ''}'>{'ok' if c['ok'] else ('FAIL' if c['hard'] else 'warn')}: {esc(c['msg'])}</li>"
                        for c in checks)
        style_chip = f"<span class='chip {st['verdict']}'>style {st['verdict']}</span>" if st else ""
        parts.append(
            f"<div class='card'><div>{raw_img}<div class='dim'>raw</div></div><div>{fin_img}<div class='dim'>final {a.size[0]}x{a.size[1]} (x{k})</div></div>"
            f"<div><div class='name'>{esc(a.name)}</div><span class='chip {verdict}'>{verdict}</span>{style_chip}"
            f"<ul>{items}</ul><details><summary>prompt</summary><pre>{esc(prompts.get(a.name, a.prompt))}</pre></details>"
            f"<div class='fb' data-n='{esc(a.name)}'><button class='okb' onclick=\"mark('{esc(a.name)}','ok',this)\">OK</button>"
            f"<button class='fixb' onclick=\"mark('{esc(a.name)}','fix',this)\">Fix</button></div>"
            f"<textarea placeholder='what is wrong / what to change' oninput=\"note('{esc(a.name)}',this.value)\"></textarea></div></div>")
    parts.append(f"<footer><button onclick='copyFb()'>Copy feedback</button><span id='cnt' class='dim'>nothing marked yet</span></footer>"
                 f"<script>const PROJECT={json.dumps(project.name)};const TOTAL={len(project.assets)};{JS}</script></body></html>")
    out = ws / "review.html"
    out.write_text("".join(parts), encoding="utf-8")
    return out
