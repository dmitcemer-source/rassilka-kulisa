"""Simple management dashboard: FastAPI JSON API + single-page HTML view."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import Settings, load_settings
from .db import Database

app = FastAPI(title="KULISA Campaign Dashboard", version="1.0.0")

HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>KULISA Campaign Dashboard</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;background:#fafafa;color:#222}
h1{border-bottom:3px solid #b3282d;padding-bottom:.4rem}
.header{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
.lang-switch button{background:#fff;border:1px solid #ccc;padding:.3rem .9rem;cursor:pointer;font-size:.9rem}
.lang-switch button.active{background:#b3282d;color:#fff;border-color:#b3282d}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin:1.5rem 0}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1rem;text-align:center}
.card .num{font-size:2rem;font-weight:700;color:#b3282d}
.card .lbl{color:#666;font-size:.85rem}
table{border-collapse:collapse;width:100%;background:#fff;margin-bottom:1rem}
td,th{border:1px solid #ddd;padding:.5rem;text-align:left;font-size:.9rem}
.flag{display:inline-block;padding:.1rem .5rem;border-radius:4px;font-size:.8rem;background:#eee}
.flag.red{background:#fdecea;color:#b3282d}.flag.green{background:#e8f5e9;color:#1b5e20}
</style></head><body>
<div class="header">
  <h1 id="title"></h1>
  <div class="lang-switch">
    <button id="btn-ru" onclick="setLang('ru')">RU</button>
    <button id="btn-en" onclick="setLang('en')">EN</button>
  </div>
</div>
<div class="grid" id="stats"></div>
<h2 id="h-campaigns"></h2><table id="campaigns"></table>
<h2 id="h-segments"></h2><table id="segments"></table>
<script>
const I18N = {
  ru: {
    title: 'KULISA Talent Network — Панель управления кампаниями',
    campaigns: 'Кампании', segments: 'Сегменты',
    cards: [
      ['Всего контактов', 'total'], ['Валидные адреса', 'valid'],
      ['Невалидные адреса', 'invalid'], ['В стоп-листе', 'suppressed'],
      ['Черновики кампаний', 'drafts'], ['Одобренные кампании', 'approved'],
      ['Отправлено писем', 'sent'], ['Ошибки доставки', 'bounced'],
      ['Ответы', 'replies'], ['Отписки', 'unsubscribed'],
      ['Жалобы', 'complained'],
    ],
    yes: 'ДА', no: 'НЕТ (заблокировано)', sending: 'Отправка включена',
    th: {id:'ID', name:'Название', status:'Статус', approved_by:'Одобрил', started:'Запущена',
         country:'Страна', language:'Язык', org_type:'Тип организации', members:'Участников'},
    not_started: 'не запускалась',
  },
  en: {
    title: 'KULISA Talent Network — Campaign Dashboard',
    campaigns: 'Campaigns', segments: 'Segments',
    cards: [
      ['Total contacts', 'total'], ['Valid emails', 'valid'],
      ['Invalid emails', 'invalid'], ['Suppressed', 'suppressed'],
      ['Campaign drafts', 'drafts'], ['Approved campaigns', 'approved'],
      ['Sent emails', 'sent'], ['Delivery failures', 'bounced'],
      ['Replies', 'replies'], ['Unsubscribes', 'unsubscribed'],
      ['Complaints', 'complained'],
    ],
    yes: 'YES', no: 'NO (locked)', sending: 'Sending enabled',
    th: {id:'ID', name:'Name', status:'Status', approved_by:'Approved by', started:'Started',
         country:'Country', language:'Language', org_type:'Org type', members:'Members'},
    not_started: 'not started',
  }
};
let LANG = localStorage.getItem('kulisa_lang') || 'ru';
let STATS = null;
function setLang(lang){
  LANG = lang;
  localStorage.setItem('kulisa_lang', lang);
  document.documentElement.lang = lang;
  document.getElementById('btn-ru').classList.toggle('active', lang==='ru');
  document.getElementById('btn-en').classList.toggle('active', lang==='en');
  render();
}
function th(t, key){ return `<th>${t[key]}</th>`; }
function render(){
  if (!STATS) return;
  const t = I18N[LANG], s = STATS;
  document.getElementById('title').textContent = t.title;
  document.getElementById('h-campaigns').textContent = t.campaigns;
  document.getElementById('h-segments').textContent = t.segments;
  const cards = t.cards.map(c => [c[0], s.contacts[c[1]] !== undefined ? s.contacts[c[1]] : s.campaigns[c[1]]]);
  cards.push([t.sending, s.safety.sending_enabled ? t.yes : t.no]);
  document.getElementById('stats').innerHTML = cards.map(c =>
    `<div class="card"><div class="num">${c[1]}</div><div class="lbl">${c[0]}</div></div>`).join('');
  const ct = t.th;
  document.getElementById('campaigns').innerHTML =
    `<tr>${th(ct,'id')}${th(ct,'name')}${th(ct,'status')}${th(ct,'approved_by')}${th(ct,'started')}</tr>` +
    s.campaigns.list.map(c =>
      `<tr><td>${c.id}</td><td>${c.name}</td><td><span class="flag ${c.status==='sent'?'green':(c.status==='approved'?'':'red')}">${c.status}</span></td><td>${c.approved_by||'-'}</td><td>${c.started_at||t.not_started}</td></tr>`).join('');
  document.getElementById('segments').innerHTML =
    `<tr>${th(ct,'id')}${th(ct,'name')}${th(ct,'country')}${th(ct,'language')}${th(ct,'org_type')}${th(ct,'members')}</tr>` +
    s.segments.map(g => `<tr><td>${g.id}</td><td>${g.name}</td><td>${g.country||'-'}</td><td>${g.language||'-'}</td><td>${g.org_type||'-'}</td><td>${g.members}</td></tr>`).join('');
}
async function load(){
  STATS = await (await fetch('/api/stats')).json();
  setLang(LANG);
}
load();
</script></body></html>"""


def compute_stats(db: Database, settings: Settings | None = None) -> dict:
    settings = settings or load_settings()
    with db.connect() as conn:
        def one(sql: str) -> int:
            return conn.execute(sql).fetchone()["n"]

        contacts = {
            "total": one("SELECT COUNT(*) AS n FROM contacts"),
            "valid": one("SELECT COUNT(*) AS n FROM contacts WHERE status='valid'"),
            "invalid": one("SELECT COUNT(*) AS n FROM contacts WHERE status='invalid'"),
            "risky": one("SELECT COUNT(*) AS n FROM contacts WHERE status='risky'"),
            "suppressed": one("SELECT COUNT(*) AS n FROM suppression_list"),
        }
        campaign_stats = {
            "drafts": one("SELECT COUNT(*) AS n FROM campaigns WHERE status IN ('draft','pending_approval')"),
            "approved": one("SELECT COUNT(*) AS n FROM campaigns WHERE status='approved'"),
            "sent": one("SELECT COALESCE(SUM(sent),0) AS n FROM campaign_stats"),
            "delivered": one("SELECT COALESCE(SUM(delivered),0) AS n FROM campaign_stats"),
            "bounced": one("SELECT COALESCE(SUM(bounced),0) AS n FROM campaign_stats"),
            "complained": one("SELECT COALESCE(SUM(complained),0) AS n FROM campaign_stats"),
            "replies": one("SELECT COUNT(*) AS n FROM replies"),
            "unsubscribed": one("SELECT COUNT(*) AS n FROM suppression_list WHERE reason='unsubscribe'"),
        }
        campaigns = conn.execute(
            "SELECT id, name, status, approved_by, started_at::date AS started_at FROM campaigns ORDER BY id"
        ).fetchall()
        segments = conn.execute(
            """SELECT s.id, s.name, s.country, s.language, s.org_type,
                      COUNT(m.contact_id) AS members
               FROM segments s LEFT JOIN segment_members m ON m.segment_id = s.id
               GROUP BY s.id ORDER BY s.id"""
        ).fetchall()
    return {
        "contacts": contacts,
        "campaigns": {**campaign_stats, "list": [dict(c) for c in campaigns]},
        "segments": [dict(s) for s in segments],
        "safety": {
            "sending_enabled": settings.sending_enabled,
            "test_mode": settings.test_mode,
        },
    }


@app.get("/api/stats")
def stats():
    return compute_stats(Database(load_settings().database_url))


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML
