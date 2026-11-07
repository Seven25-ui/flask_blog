# ==========================================================================
# DATING APP ADDITIONS para sa app.py   (VERSION 2)
# Gamita sa BAG-ONG repo + BAG-ONG Neon database/branch (para ma-create ang
# bag-ong columns sa User). Ayaw ni i-deploy sa live nga flask_blog.
#
# Karon, tanan REAL CODE na (dili na comments). Ang mga "ILISI" nga functions
# mopuli sa parehas nga ngalan nga function sa imong app.py.
# ==========================================================================

# --------------------------------------------------------------------------
# 0) IMPORTS (idugang sa taas sa app.py)
# --------------------------------------------------------------------------
from sqlalchemy import or_, and_, func


# --------------------------------------------------------------------------
# A) MODELS
# --------------------------------------------------------------------------
# 1) Idugang kini nga columns sa sulod sa class User:
#
#     birthdate     = db.Column(db.Date, nullable=True)
#     gender        = db.Column(db.String(20), nullable=True)       # male / female / other
#     looking_for   = db.Column(db.String(20), default='everyone')  # male / female / other / everyone
#     location_text = db.Column(db.String(100), nullable=True)      # city lang, dili exact address
#     interests     = db.Column(db.String(200), nullable=True)
#
# 2) Bag-ong tables (ibutang human sa Notification model):

class Swipe(db.Model):
    __table_args__ = (db.UniqueConstraint('swiper_id', 'target_id'),)
    id = db.Column(db.Integer, primary_key=True)
    swiper_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    liked = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


class Match(db.Model):
    __table_args__ = (db.UniqueConstraint('user_a_id', 'user_b_id'),)
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # mas gamay nga id
    user_b_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


class Block(db.Model):
    __table_args__ = (db.UniqueConstraint('blocker_id', 'blocked_id'),)
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reported_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=ph_time)


# --------------------------------------------------------------------------
# B) HELPERS (ibutang human sa notify()/upload_media() helpers)
# --------------------------------------------------------------------------
def calc_age(birthdate):
    if not birthdate:
        return None
    today = ph_time().date()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


def are_matched(a, b):
    lo, hi = sorted((a, b))
    return Match.query.filter_by(user_a_id=lo, user_b_id=hi).first() is not None


def is_blocked(a, b):
    """True kung si a nag-block kang b o si b nag-block kang a."""
    return Block.query.filter(
        or_(and_(Block.blocker_id == a, Block.blocked_id == b),
            and_(Block.blocker_id == b, Block.blocked_id == a))
    ).first() is not None


def match_partners(user_id):
    """Tanang matched nga users (wala na-block), pinaka-bag-o una."""
    rows = (Match.query.filter(or_(Match.user_a_id == user_id, Match.user_b_id == user_id))
            .order_by(Match.created_at.desc()).all())
    people = []
    for m in rows:
        other_id = m.user_b_id if m.user_a_id == user_id else m.user_a_id
        other = db.session.get(User, other_id)
        if other and not is_blocked(user_id, other_id):
            people.append(other)
    return people


app.jinja_env.globals.update(calc_age=calc_age)


# --------------------------------------------------------------------------
# C) ILISI: register()  -- naay 18+ check ug gender/looking_for
# --------------------------------------------------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash("Ayaw kalimti ang username ug password!")
            return redirect(url_for('register'))
        if not USERNAME_RE.fullmatch(username):
            flash("Username: letters, numbers, underscore ra, 3-20 ka characters.")
            return redirect(url_for('register'))
        if len(password) < 6:
            flash("Ang password kinahanglan labing menos 6 ka characters.")
            return redirect(url_for('register'))
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash("Naa na nay naggamit sa maong username. Pagpili og lain.")
            return redirect(url_for('register'))

        # --- Dating fields ---
        try:
            birthdate = datetime.strptime(request.form.get('birthdate', ''), '%Y-%m-%d').date()
        except ValueError:
            flash("Ibutang ang saktong birthdate.")
            return redirect(url_for('register'))
        age = calc_age(birthdate)
        if age < 18:
            flash("18 anyos pataas ra ang pwede.")
            return redirect(url_for('register'))
        if age > 100:
            flash("Ibutang ang saktong birthdate.")
            return redirect(url_for('register'))

        gender = request.form.get('gender')
        if gender not in ('male', 'female', 'other'):
            flash("Pilia ang imong gender.")
            return redirect(url_for('register'))
        looking_for = request.form.get('looking_for', 'everyone')
        if looking_for not in ('male', 'female', 'other', 'everyone'):
            looking_for = 'everyone'

        is_first = User.query.count() == 0
        db.session.add(User(username=username, password=generate_password_hash(password),
                            is_admin=is_first, birthdate=birthdate,
                            gender=gender, looking_for=looking_for))
        db.session.commit()
        flash("Rehistrado na ka! Pwede na ka mo-login.")
        return redirect(url_for('login'))
    return render_template('register.html')


# --------------------------------------------------------------------------
# D) ILISI: profile_settings()  -- nasave na ang bag-ong fields
#    (ang birthdate DILI editable, para dili malingla ang 18+)
# --------------------------------------------------------------------------
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = current_user()
    if request.method == 'POST':
        try:
            user.bio = (request.form.get('bio') or '')[:500]
            user.location_text = (request.form.get('location_text') or '').strip()[:100] or None
            user.interests = (request.form.get('interests') or '').strip()[:200] or None

            gender = request.form.get('gender')
            if gender in ('male', 'female', 'other'):
                user.gender = gender
            looking_for = request.form.get('looking_for')
            if looking_for in ('male', 'female', 'other', 'everyone'):
                user.looking_for = looking_for

            for field, attr in (('profile_pic', 'profile_pic'), ('background_pic', 'background_pic')):
                f = request.files.get(field)
                if f and f.filename:
                    url, _ = upload_media(f, allow_video=False)
                    setattr(user, attr, url)
            db.session.commit()
            return redirect(url_for('user_profile', username=user.username))
        except Exception as e:
            db.session.rollback()
            flash(f"Naay error sa pag-save: {e}")
    return render_template('profile_settings.html', user=user)


# --------------------------------------------------------------------------
# E) ROUTES: discover / swipe / matches / block / report
# --------------------------------------------------------------------------
@app.route('/discover')
@login_required
def discover():
    me = current_user()
    swiped = db.session.query(Swipe.target_id).filter(Swipe.swiper_id == me.id)
    blocked_by_me = db.session.query(Block.blocked_id).filter(Block.blocker_id == me.id)
    blocked_me = db.session.query(Block.blocker_id).filter(Block.blocked_id == me.id)

    q = User.query.filter(
        User.id != me.id,
        User.birthdate.isnot(None),
        User.username != 'admin',
        ~User.id.in_(swiped),
        ~User.id.in_(blocked_by_me),
        ~User.id.in_(blocked_me),
    )
    # Ang gusto nako
    if me.looking_for in ('male', 'female', 'other'):
        q = q.filter(User.gender == me.looking_for)
    # Ug ang gusto nila (mutual): dili ka ipakita sa mga dili interesado sa imong gender
    if me.gender:
        q = q.filter(or_(User.looking_for == 'everyone',
                         User.looking_for == me.gender,
                         User.looking_for.is_(None)))

    candidate = q.order_by(func.random()).first()
    return render_template('discover.html', candidate=candidate, user=me)


@app.route('/swipe/<int:target_id>', methods=['POST'])
@login_required
def swipe(target_id):
    me = current_user()
    if target_id == me.id or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    if is_blocked(me.id, target_id):
        return {"error": "blocked"}, 403

    data = request.get_json(silent=True) or {}
    liked = bool(data.get('liked'))

    if Swipe.query.filter_by(swiper_id=me.id, target_id=target_id).first():
        return {"matched": False}          # na-swipe na, ayaw i-doble

    matched = False
    try:
        db.session.add(Swipe(swiper_id=me.id, target_id=target_id, liked=liked))
        if liked:
            they_liked = Swipe.query.filter_by(swiper_id=target_id, target_id=me.id, liked=True).first()
            if they_liked and not are_matched(me.id, target_id):
                lo, hi = sorted((me.id, target_id))
                db.session.add(Match(user_a_id=lo, user_b_id=hi))
                matched = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Swipe error: {e}")
        return {"error": "failed"}, 500

    if matched:
        other = db.session.get(User, target_id)
        # I-notify ang duha ka side
        socketio.emit('notify', {'message': f"💘 It's a match with {me.username}!", 'type': 'match'},
                      room=f"user_{target_id}")
        socketio.emit('notify', {'message': f"💘 It's a match with {other.username}!", 'type': 'match'},
                      room=f"user_{me.id}")
        return {"matched": True, "username": other.username}
    return {"matched": False}


@app.route('/matches')
@login_required
def matches():
    me = current_user()
    return render_template('matches.html', people=match_partners(me.id), user=me)


@app.route('/block/<int:target_id>', methods=['POST'])
@login_required
def block_user(target_id):
    me_id = session['user_id']
    if target_id == me_id or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    if not Block.query.filter_by(blocker_id=me_id, blocked_id=target_id).first():
        db.session.add(Block(blocker_id=me_id, blocked_id=target_id))
        db.session.commit()
    return {"status": "blocked"}


@app.route('/report/<int:target_id>', methods=['POST'])
@login_required
def report_user(target_id):
    reason = ((request.get_json(silent=True) or {}).get('reason') or '').strip()[:300]
    if not reason or not db.session.get(User, target_id):
        return {"error": "invalid"}, 400
    db.session.add(Report(reporter_id=session['user_id'], reported_id=target_id, reason=reason))
    db.session.commit()
    return {"status": "reported"}


# --------------------------------------------------------------------------
# F) ILISI: inbox() ug send_message()  -- matches ra ang pwede ma-chat
#    (parehas gihapon ang variables sa messages.html: partners, active_chat,
#     selected_user, user, active_tab)
# --------------------------------------------------------------------------
@app.route('/messages')
@app.route('/messages/<int:user_id>')
@login_required
def inbox(user_id=None):
    me_id = session['user_id']
    me = current_user()

    # Ang partners kay ang mga matches (bisan wala pa magsinultihanay)
    partners = match_partners(me_id)

    active_chat, selected_user = [], None
    if user_id:
        if not are_matched(me_id, user_id) or is_blocked(me_id, user_id):
            flash("Matches ra ang pwede ma-chat.")
            return redirect(url_for('matches'))

        selected_user = db.session.get(User, user_id)
        if selected_user:
            active_chat = Message.query.filter(
                ((Message.sender_id == me_id) & (Message.receiver_id == user_id)) |
                ((Message.sender_id == user_id) & (Message.receiver_id == me_id))
            ).order_by(Message.created_at.asc()).all()
            for m in Message.query.filter_by(sender_id=user_id, receiver_id=me_id, is_read=False).all():
                m.is_read = True
            db.session.commit()

    return render_template('messages.html', partners=partners, active_chat=active_chat,
                           selected_user=selected_user, user=me, active_tab='messages')


@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    me = current_user()
    content = (request.form.get('content') or '').strip()[:2000]
    parent_id = request.form.get('parent_id')

    if not db.session.get(User, receiver_id):
        return redirect(url_for('matches'))
    # Matches ra, ug dili kung naay block
    if not are_matched(me.id, receiver_id) or is_blocked(me.id, receiver_id):
        return "Matches ra ang pwede ma-chat.", 403
    if not content:
        return redirect(request.referrer or url_for('inbox', user_id=receiver_id))

    p_id = int(parent_id) if parent_id and parent_id.isdigit() else None
    try:
        db.session.add(Message(sender_id=me.id, receiver_id=receiver_id,
                               content=content, parent_id=p_id))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        return "Error sending message.", 500

    # Real-time toast sa nakadawat
    socketio.emit('notify', {'message': f'💬 {me.username}: {content[:40]}', 'type': 'message'},
                  room=f"user_{receiver_id}")
    return redirect(url_for('inbox', user_id=receiver_id))


# --------------------------------------------------------------------------
# G) IDUGANG sa admin_delete_user()  -- importante!
#    Kung dili, mo-error ang pag-delete sa user nga naay swipes/matches (foreign key).
#    Ibutang kini tapad sa Follow.query...delete() line:
#
#     Swipe.query.filter((Swipe.swiper_id == user_id) | (Swipe.target_id == user_id)).delete()
#     Match.query.filter((Match.user_a_id == user_id) | (Match.user_b_id == user_id)).delete()
#     Block.query.filter((Block.blocker_id == user_id) | (Block.blocked_id == user_id)).delete()
#     Report.query.filter((Report.reporter_id == user_id) | (Report.reported_id == user_id)).delete()
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# H) DB TABLES: ibutang sa ilawom sa dili pa ang `if __name__ == '__main__':`
# --------------------------------------------------------------------------
with app.app_context():
    db.create_all()
