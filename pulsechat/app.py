from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random, string, re, os, time, hashlib, uuid

app = Flask(__name__, static_folder='static')
app.secret_key = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "zynx.messanger@gmail.com"
SMTP_PASS = "opky ibwo rkok fwkv"
# ─────────────────────────────────────────────────────────────────────────────

users_db      = {}
pending_codes = {}
messages_db   = {}
online        = {}
profiles_db   = {}
friends_db    = {}

AVATAR_COLORS = ['#7c5cfc','#fc5cbc','#f59e0b','#10b981','#3b82f6','#ef4444','#8b5cf6','#06b6d4']
AVATAR_EMOJIS = ['🎮','👾','🔥','⚡','🦊','🐺','🐉','👻','🤖','💀','🦁','🐯']

BANNED = [
    r'бля',r'блять',r'ёб',r'еб[аоуиё]',r'[еэ]бл[аяоуи]',
    r'пизд',r'хуй',r'хуе',r'хуя',r'хуё',r'пидор',r'пидар',
    r'ёбан',r'еблан',r'сука',r'шлюх',r'мудак',r'гандон',
    r'нахуй',r'похуй',r'пиздец',r'блядь',r'бляд',r'ублюд',
    r'fuck',r'shit',r'bitch',r'asshole',r'cunt',
    r'nigger',r'nigga',r'faggot',r'whore',r'slut',r'motherfuck',
    r'pdf',r'free.*crack',r'warez',
    r'admin',r'administrator',r'moderator',r'support',r'root',r'system',r'official',
]

def nick_ok(n):
    lo = n.lower()
    for p in BANNED:
        if re.search(p, lo): return False, "Никнейм содержит запрещённые слова."
    if len(n) < 3:  return False, "Никнейм слишком короткий (мин. 3)."
    if len(n) > 24: return False, "Никнейм слишком длинный (макс. 24)."
    if not re.match(r'^[a-zA-Zа-яёА-ЯЁ0-9_.\-]+$', n):
        return False, "Только буквы, цифры, _, . и -"
    return True, ""

def pass_ok(p):
    if len(p) < 8:  return False, "Пароль минимум 8 символов."
    if len(p) > 50: return False, "Пароль максимум 50 символов."
    if not re.search(r'[A-Z]', p): return False, "Нужна заглавная буква."
    if not re.search(r'[0-9]', p): return False, "Нужна цифра."
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{};\':"\\|,.<>\/?`~]', p):
        return False, "Нужен спецсимвол (!@#$ и т.д.)"
    return True, ""

def email_ok(e): return bool(re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', e))
def hashpw(p):   return hashlib.sha256(p.encode()).hexdigest()
def mkcode():    return ''.join(random.choices(string.digits, k=6))
def conv_key(a, b): return '__'.join(sorted([a.lower(), b.lower()]))

def get_nick_by_name(nickname):
    for email, u in users_db.items():
        if u.get('nickname','').lower() == nickname.lower() and u.get('verified'):
            return email
    return None

def ensure_friends(nick):
    if nick not in friends_db:
        friends_db[nick] = {'friends': set(), 'sent': set(), 'received': set(), 'blocked': set()}

def ensure_profile(nick):
    if nick not in profiles_db:
        profiles_db[nick] = {
            'avatar_color': random.choice(AVATAR_COLORS),
            'avatar_emoji': random.choice(AVATAR_EMOJIS),
        }

def get_profile(nick):
    ensure_profile(nick)
    p = profiles_db[nick]
    return {
        'avatar_color': p.get('avatar_color', '#7c5cfc'),
        'avatar_emoji': p.get('avatar_emoji', '🎮'),
    }

def send_email(to, nickname, code):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Zynx — код подтверждения: {code}"
        msg['From']    = f"Zynx <{SMTP_USER}>"
        msg['To']      = to
        html = f"""<html><body style="background:#07070e;font-family:sans-serif;padding:40px 20px;">
<div style="max-width:460px;margin:0 auto;background:#141420;border-radius:16px;border:1px solid #252535;overflow:hidden;">
  <div style="background:linear-gradient(135deg,#7c5cfc,#fc5cbc);padding:28px;text-align:center;">
    <h1 style="color:#fff;margin:0;letter-spacing:3px;font-size:24px;">ZYNX</h1>
  </div>
  <div style="padding:32px;">
    <p style="color:#c0c0d0;">Привет, <b style="color:#fff">{nickname}</b>! 👋</p>
    <p style="color:#888;">Твой код подтверждения:</p>
    <div style="background:#1e1e2e;border:2px solid #7c5cfc;border-radius:12px;padding:22px;text-align:center;margin:20px 0;">
      <span style="font-size:40px;font-weight:900;letter-spacing:14px;color:#a78bfa;font-family:monospace;">{code}</span>
    </div>
    <p style="color:#666;font-size:12px;">Код действует 10 минут.</p>
  </div>
</div></body></html>"""
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, to, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}"); return False

@app.route('/')
def index(): return send_from_directory('static', 'index.html')

@app.route('/api/register', methods=['POST'])
def register():
    d = request.get_json() or {}
    email    = (d.get('email') or '').strip().lower()
    nickname = (d.get('nickname') or '').strip()
    password =  d.get('password') or ''
    if not email_ok(email): return jsonify({'ok':False,'error':'Неверный формат email.'}),400
    if email in users_db and users_db[email].get('verified'):
        return jsonify({'ok':False,'error':'Email уже зарегистрирован.'}),409
    ok,err = nick_ok(nickname)
    if not ok: return jsonify({'ok':False,'error':err}),400
    for u in users_db.values():
        if u.get('nickname','').lower()==nickname.lower() and u.get('verified'):
            return jsonify({'ok':False,'error':'Никнейм уже занят.'}),409
    ok,err = pass_ok(password)
    if not ok: return jsonify({'ok':False,'error':err}),400
    code = mkcode()
    pending_codes[email] = {'code':code,'expires_at':time.time()+600,'nickname':nickname,'password_hash':hashpw(password)}
    if not send_email(email, nickname, code):
        return jsonify({'ok':False,'error':'Не удалось отправить письмо.'}),500
    return jsonify({'ok':True})

@app.route('/api/verify', methods=['POST'])
def verify():
    d = request.get_json() or {}
    email = (d.get('email') or '').strip().lower()
    code  = (d.get('code') or '').strip()
    p = pending_codes.get(email)
    if not p: return jsonify({'ok':False,'error':'Нет активного кода.'}),400
    if time.time() > p['expires_at']:
        del pending_codes[email]; return jsonify({'ok':False,'error':'Код истёк.'}),400
    if p['code'] != code: return jsonify({'ok':False,'error':'Неверный код.'}),400
    users_db[email] = {'nickname':p['nickname'],'password_hash':p['password_hash'],'verified':True,'created_at':time.time()}
    ensure_friends(p['nickname'])
    ensure_profile(p['nickname'])
    del pending_codes[email]
    return jsonify({'ok':True,'nickname':p['nickname']})

@app.route('/api/resend', methods=['POST'])
def resend():
    d = request.get_json() or {}
    email = (d.get('email') or '').strip().lower()
    p = pending_codes.get(email)
    if not p: return jsonify({'ok':False,'error':'Нет активной регистрации.'}),400
    code = mkcode()
    pending_codes[email].update({'code':code,'expires_at':time.time()+600})
    if not send_email(email, p['nickname'], code):
        return jsonify({'ok':False,'error':'Не удалось отправить письмо.'}),500
    return jsonify({'ok':True})

@app.route('/api/login', methods=['POST'])
def login():
    d = request.get_json() or {}
    email    = (d.get('email') or '').strip().lower()
    password =  d.get('password') or ''
    u = users_db.get(email)
    if not u or not u.get('verified'): return jsonify({'ok':False,'error':'Пользователь не найден.'}),404
    if u['password_hash'] != hashpw(password): return jsonify({'ok':False,'error':'Неверный пароль.'}),401
    ensure_friends(u['nickname'])
    ensure_profile(u['nickname'])
    return jsonify({'ok':True,'nickname':u['nickname']})

@app.route('/api/users')
def get_users():
    result = []
    for u in users_db.values():
        if u.get('verified'):
            nick = u['nickname']
            p = get_profile(nick)
            result.append({'nickname':nick,'online':nick in online,'avatar_color':p['avatar_color'],'avatar_emoji':p['avatar_emoji']})
    return jsonify(result)

@app.route('/api/history')
def get_history():
    a      = (request.args.get('a') or '').strip()
    b      = (request.args.get('b') or '').strip()
    viewer = (request.args.get('viewer') or '').strip()
    if not a or not b: return jsonify([])
    msgs = messages_db.get(conv_key(a,b),[])
    return jsonify([{k:v for k,v in m.items() if k!='deleted_for'} for m in msgs if viewer not in m.get('deleted_for',[])])

@app.route('/api/profile', methods=['GET'])
def get_profile_api():
    nick = (request.args.get('nick') or '').strip()
    if not nick: return jsonify({'ok':False}),400
    p = get_profile(nick)
    created_at = None
    for u in users_db.values():
        if u.get('nickname','').lower()==nick.lower():
            created_at=u.get('created_at'); break
    return jsonify({'ok':True,'profile':{**p,'nickname':nick,'online':nick in online,'created_at':created_at}})

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    d = request.get_json() or {}
    nick = (d.get('nickname') or '').strip()
    if not nick: return jsonify({'ok':False,'error':'Нет никнейма.'}),400
    ensure_profile(nick)
    p = profiles_db[nick]
    if 'avatar_color' in d and d['avatar_color'] in AVATAR_COLORS:
        p['avatar_color'] = d['avatar_color']
    if 'avatar_emoji' in d and d['avatar_emoji'] in AVATAR_EMOJIS:
        p['avatar_emoji'] = d['avatar_emoji']
    pub = get_profile(nick)
    # Правильный способ emit из REST endpoint
    socketio.emit('profile_updated', {'nickname': nick, 'profile': pub})
    return jsonify({'ok':True})

@app.route('/api/friends', methods=['GET'])
def get_friends():
    nick = (request.args.get('nick') or '').strip()
    if not nick: return jsonify({'ok':False}),400
    ensure_friends(nick)
    fd = friends_db[nick]
    friends_list = []
    for n in fd['friends']:
        p = get_profile(n)
        friends_list.append({'nickname':n,'online':n in online,'avatar_color':p['avatar_color'],'avatar_emoji':p['avatar_emoji']})
    return jsonify({'ok':True,'friends':friends_list,'sent':list(fd['sent']),'received':list(fd['received']),'blocked':list(fd['blocked'])})

@app.route('/api/friends/send', methods=['POST'])
def send_friend_request():
    d = request.get_json() or {}
    me     = (d.get('from') or '').strip()
    target = (d.get('to') or '').strip()
    if not me or not target: return jsonify({'ok':False,'error':'Нет данных.'}),400
    if me.lower()==target.lower(): return jsonify({'ok':False,'error':'Нельзя добавить себя.'}),400
    if not get_nick_by_name(target): return jsonify({'ok':False,'error':'Пользователь не найден.'}),404
    ensure_friends(me); ensure_friends(target)
    fm=friends_db[me]; ft=friends_db[target]
    if target in fm['blocked']: return jsonify({'ok':False,'error':'Пользователь заблокирован.'}),400
    if me in ft['blocked']:     return jsonify({'ok':False,'error':'Невозможно отправить заявку.'}),400
    if target in fm['friends']: return jsonify({'ok':False,'error':'Уже в друзьях.'}),400
    if target in fm['sent']:    return jsonify({'ok':False,'error':'Заявка уже отправлена.'}),400
    if me in ft['sent']:
        ft['sent'].discard(me); fm['received'].discard(target)
        fm['friends'].add(target); ft['friends'].add(me)
        for n in [me,target]:
            sid=online.get(n)
            if sid: socketio.emit('friends_update',{},to=sid)
        return jsonify({'ok':True,'message':f'Вы теперь друзья с {target}!'})
    fm['sent'].add(target); ft['received'].add(me)
    rsid=online.get(target)
    if rsid: socketio.emit('friend_request',{'from':me},to=rsid)
    return jsonify({'ok':True,'message':f'Заявка отправлена {target}!'})

@app.route('/api/friends/accept', methods=['POST'])
def accept_friend():
    d=request.get_json() or {}
    me=(d.get('me') or '').strip(); sender=(d.get('from') or '').strip()
    ensure_friends(me); ensure_friends(sender)
    fm=friends_db[me]; fs=friends_db[sender]
    if sender not in fm['received']: return jsonify({'ok':False,'error':'Заявки нет.'}),400
    fm['received'].discard(sender); fs['sent'].discard(me)
    fm['friends'].add(sender); fs['friends'].add(me)
    for n in [me,sender]:
        sid=online.get(n)
        if sid: socketio.emit('friends_update',{},to=sid)
    return jsonify({'ok':True})

@app.route('/api/friends/decline', methods=['POST'])
def decline_friend():
    d=request.get_json() or {}
    me=(d.get('me') or '').strip(); sender=(d.get('from') or '').strip()
    ensure_friends(me); ensure_friends(sender)
    friends_db[me]['received'].discard(sender); friends_db[sender]['sent'].discard(me)
    return jsonify({'ok':True})

@app.route('/api/friends/block', methods=['POST'])
def block_user():
    d=request.get_json() or {}
    me=(d.get('me') or '').strip(); target=(d.get('target') or '').strip()
    ensure_friends(me); ensure_friends(target)
    fm=friends_db[me]; ft=friends_db[target]
    fm['friends'].discard(target); ft['friends'].discard(me)
    fm['sent'].discard(target); ft['received'].discard(me)
    fm['received'].discard(target); ft['sent'].discard(me)
    fm['blocked'].add(target)
    sid=online.get(me)
    if sid: socketio.emit('friends_update',{},to=sid)
    return jsonify({'ok':True})

@app.route('/api/friends/unblock', methods=['POST'])
def unblock_user():
    d=request.get_json() or {}
    me=(d.get('me') or '').strip(); target=(d.get('target') or '').strip()
    ensure_friends(me); friends_db[me]['blocked'].discard(target)
    return jsonify({'ok':True})

@app.route('/api/messages/delete', methods=['POST'])
def delete_message():
    d=request.get_json() or {}
    msg_id=(d.get('id') or '').strip()
    nickname=(d.get('nickname') or '').strip()
    mode=d.get('mode','me')
    for key,msgs in messages_db.items():
        for m in msgs:
            if m.get('id')==msg_id:
                if mode=='all':
                    if m.get('from')!=nickname: return jsonify({'ok':False,'error':'Нельзя удалить чужое.'}),403
                    m['deleted_for']=['__all__']; m['text']='🗑 Сообщение удалено'; m['type']='text'
                    for n in [m['from'],m['to']]:
                        sid=online.get(n)
                        if sid: socketio.emit('message_deleted',{'id':msg_id,'text':'🗑 Сообщение удалено'},to=sid)
                else:
                    if 'deleted_for' not in m: m['deleted_for']=[]
                    if nickname not in m['deleted_for']: m['deleted_for'].append(nickname)
                return jsonify({'ok':True})
    return jsonify({'ok':False,'error':'Не найдено.'}),404

@socketio.on('join')
def on_join(data):
    nickname=(data.get('nickname') or '').strip()
    if not nickname: return
    online[nickname]=request.sid
    ensure_friends(nickname); ensure_profile(nickname)
    emit('user_status',{'nickname':nickname,'online':True},broadcast=True)
    # Шлём снапшот профилей онлайн юзеров
    snap={n:get_profile(n) for n in online}
    emit('profiles_snapshot',snap)

@socketio.on('disconnect')
def on_disconnect():
    for n,sid in list(online.items()):
        if sid==request.sid:
            del online[n]
            emit('user_status',{'nickname':n,'online':False},broadcast=True)
            break

@socketio.on('private_message')
def on_private_message(data):
    sender=(data.get('from') or '').strip()
    receiver=(data.get('to') or '').strip()
    text=(data.get('text') or '').strip()
    msg_type=data.get('type','text')
    if not sender or not receiver or not text: return
    if msg_type=='text' and len(text)>2000: return
    ensure_friends(sender); ensure_friends(receiver)
    if receiver in friends_db[sender]['blocked']: return
    if sender in friends_db[receiver]['blocked']: return
    msg={'id':str(uuid.uuid4())[:8],'from':sender,'to':receiver,'text':text,'type':msg_type,'time':int(time.time()*1000),'deleted_for':[]}
    key=conv_key(sender,receiver)
    messages_db.setdefault(key,[]).append(msg)
    if len(messages_db[key])>500: messages_db[key]=messages_db[key][-500:]
    out={k:v for k,v in msg.items() if k!='deleted_for'}
    emit('new_message',out,to=request.sid)
    rsid=online.get(receiver)
    if rsid and rsid!=request.sid: emit('new_message',out,to=rsid)

@socketio.on('typing')
def on_typing(data):
    rsid=online.get((data.get('to') or '').strip())
    if rsid: emit('typing',{'from':data.get('from','')},to=rsid)

@socketio.on('stop_typing')
def on_stop_typing(data):
    rsid=online.get((data.get('to') or '').strip())
    if rsid: emit('stop_typing',{'from':data.get('from','')},to=rsid)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)