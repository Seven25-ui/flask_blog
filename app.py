from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import re
from datetime import datetime
from functools import wraps

# Cloudinary Imports
import cloudinary
import cloudinary.uploader
from cloudinary.uploader import upload  # Gidugang para diretso na upload() sa routes

app = Flask(__name__)
app.secret_key = "aloy_super_secret_key_733"

# --- 1. CONFIG ---
# (Pabilin imong Cloudinary ug DB config)
cloudinary.config(
    cloud_name = "dzwn8b3ax",
    api_key = "179391797818159",
    api_secret = "DfNDDAsqR2dAy4KH8sZa2_P7x2g",
    secure = True
)

raw_url = "postgresql://neondb_owner:npg_kqEm6hxCyWj2@ep-fragrant-moon-a18v84gz-pooler.ap-southeast-1.aws.neon.tech/neondb"

def fix_uri(uri):
    return uri.replace("postgres://", "postgresql+pg8000://", 1).replace("postgresql://", "postgresql+pg8000://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = fix_uri(raw_url)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 2. MODELS ---

class User(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    profile_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/avatar.png')
    # Mao ni ang atong gidugang para sa background banner
    background_pic = db.Column(db.String(500), default='https://res.cloudinary.com/demo/image/upload/v1/sample.jpg')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Post(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    
    # KANI NGA LINE ANG IDUGANG
    hashtags = db.Column(db.String(200), nullable=True) 
    
    slug = db.Column(db.String(200), unique=True, nullable=False)
    author = db.Column(db.String(80), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    media_file = db.Column(db.String(500), nullable=True)
    media_type = db.Column(db.String(10), nullable=True)
    # ... (relationships pabilin ra)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), default='like')

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='user_comments')

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')



# --- 3. HELPERS & UTILITIES ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def utility_processor():
    def get_user_by_username(username):
        return User.query.filter_by(username=username).first()

    def get_read_time(content):
        words_per_minute = 200
        words = len(content.split())
        return max(1, round(words / words_per_minute))

    def time_ago(date):
        if not date: return ""
        now = datetime.utcnow()
        diff = now - date
        periods = (
            (diff.days // 365, "year", "years"),
            (diff.days // 30, "month", "months"),
            (diff.days // 7, "week", "weeks"),
            (diff.days, "day", "days"),
            (diff.seconds // 3600, "hour", "hours"),
            (diff.seconds // 60, "minute", "minutes"),
            (diff.seconds, "second", "seconds"),
        )
        for period, singular, plural in periods:
            if period >= 1:
                return f"{period} {singular if period == 1 else plural} ago"
        return "just now"

    def user_has_liked(user_id, post_id):
        if not user_id: return False
        return Like.query.filter_by(user_id=user_id, post_id=post_id).first() is not None

    def get_like_count(post_id):
        return Like.query.filter_by(post_id=post_id).count()

    def get_comment_count(post_id):
        return Comment.query.filter_by(post_id=post_id).count()

    def get_comments_for_post(post_id):
        return Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

    def get_follower_count(user_id):
        return Follow.query.filter_by(followed_id=user_id).count()

    def is_following(follower_id, followed_id):
        if not follower_id: return False
        return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None

    return dict(
        get_user_by_username=get_user_by_username,
        get_read_time=get_read_time,
        time_ago=time_ago,
        user_has_liked=user_has_liked,
        get_like_count=get_like_count,
        get_comment_count=get_comment_count,
        get_comments_for_post=get_comments_for_post,
        get_follower_count=get_follower_count,
        is_following=is_following
    )

# --- 4. ROUTES ---

@app.route('/')
def public_home():
    tab = request.args.get('tab', 'discover')
    user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    
    if tab == 'video':
        posts = Post.query.filter_by(approved=True, media_type='video').order_by(Post.created_at.desc()).all()
    elif tab == 'following' and user:
        followed_ids = [f.followed_id for f in Follow.query.filter_by(follower_id=user.id).all()]
        posts = Post.query.filter(Post.author_id.in_(followed_ids), Post.approved==True).order_by(Post.created_at.desc()).all()
    else:
        posts = Post.query.filter_by(approved=True).order_by(Post.created_at.desc()).all()

    return render_template('home_public.html', posts=posts, user=user, active_tab=tab)

# BAG-O: CHANGE PASSWORD ROUTE
@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        old_pw = request.form.get('old_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')
        
        if not check_password_hash(user.password, old_pw):
            flash("Sayop imong karaan nga password!", "error")
        elif new_pw != confirm_pw:
            flash("Dili parehas ang new password ug confirm password!", "error")
        else:
            user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash("Success! Na-ilis na imong password.", "success")
            return redirect(url_for('profile_settings'))
    return render_template('change_password.html', user=user)

# (Ubang routes: register, login, dashboard, create_post, edit, delete, approve, reject, settings, logout, user_profile, like, comment, follow pabilin tanan)
# ... [Ang imong existing routes dri nga part] ...

@app.route('/register', methods=['GET', 'POST'])      
def register():                                           
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')                                                                    
        if not username or not password:
            flash("Ayaw kalimti ang username ug password!")                                                             
            return redirect(url_for('register'))
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:                                                                     
            flash("Naa na nay naggamit sa maong username. Pagpili og lain.")
            return redirect(url_for('register'))      
        hashed_pw = generate_password_hash(password)
        is_first = User.query.count() == 0
        new_user = User(username=username, password=hashed_pw, is_admin=is_first)
        db.session.add(new_user)
        db.session.commit()                                                                   
        flash("Rehistrado na ka! Pwede na ka mo-login.")                                                            
        return redirect(url_for('login'))              
    return render_template('register.html')            

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()                                      
        if user and check_password_hash(user.password, request.form['password']):
            session.clear()                                                                      
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        flash("Sayop ang imong username o password.")
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
    posts = Post.query.all() if user.is_admin else Post.query.filter_by(author=user.username).all()
    return render_template('my_dashboard.html', posts=posts, user=user)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    user = db.session.get(User, session['user_id'])
    if request.method == 'POST':
        title = request.form.get('title')             
        content = request.form.get('content')         
        
        # 1. KUHAON ANG HASHTAGS GIKAN SA HTML FORM
        hashtags = request.form.get('hashtags') 
        
        slug = re.sub(r'[^a-zA-Z0-9 ]', '', title).replace(" ", "-").lower() + "-" + str(int(datetime.utcnow().timestamp()))
        media_url, media_type = None, None                                                                   
        
        if 'media_file' in request.files:
            file = request.files['media_file']
            if file and file.filename != '':          
                res = cloudinary.uploader.upload(file, resource_type="auto")
                media_url = res.get('secure_url')
                media_type = 'video' if 'video' in str(res.get('resource_type')) else 'image'

        # 2. I-SAVE ANG HASHTAGS SA DATABASE (I-apil sa Post object)
        new_post = Post(
            title=title, 
            content=content, 
            hashtags=hashtags, # <--- Gidugang ni
            slug=slug, 
            author=user.username, 
            author_id=user.id,
            approved=user.is_admin, 
            media_file=media_url, 
            media_type=media_type
        )                
        
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('dashboard'))
        
    return render_template('create_post.html')

@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    # 1. Kuhaon ang post ug ang current user
    post = Post.query.get_or_404(post_id)
    user = db.session.get(User, session['user_id'])
    
    # 2. Security Check: Siguroa nga tag-iya o admin ang nag-edit
    if post.author != user.username and not user.is_admin: 
        return "Unauthorized", 403
        
    if request.method == 'POST':
        # 3. Update ang text content
        post.title = request.form.get('title')        
        post.content = request.form.get('content')
        
        # 4. Handle Media Update (Image o Video)
        file = request.files.get('media_file') 
        if file and file.filename != '':
            try:
                # I-upload ang bag-ong file sa Cloudinary
                upload_result = upload(file) 
                
                # I-save ang bag-ong URL
                post.media_file = upload_result['secure_url']
                
                # I-check kon image ba o video ang gi-upload
                if 'video' in file.mimetype:
                    post.media_type = 'video'
                else:
                    post.media_type = 'image'
            except Exception as e:
                flash(f"Error uploading media: {str(e)}", "danger")
                return render_template('edit_post.html', post=post)

        # 5. I-save ang tanang kausaban sa database
        db.session.commit()
        flash("Post updated successfully!", "success")
        return redirect(url_for('dashboard'))         
        
    # I-load ang edit page kon GET request
    return render_template('edit_post.html', post=post)

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required                                       
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)                 
    user = db.session.get(User, session['user_id'])
    if post.author == user.username or user.is_admin:
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))             

@app.route('/approve/<int:post_id>', methods=['POST']) # <--- Kani ang importante nga naay POST
@login_required
def approve_post(post_id):
    user = db.session.get(User, session['user_id'])
    if user.is_admin:
        post = Post.query.get_or_404(post_id)
        post.approved = True
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/reject/<int:post_id>')
@login_required
def reject_post(post_id):
    user = db.session.get(User, session['user_id'])
    if user.is_admin:
        post = Post.query.get_or_404(post_id)                 
        db.session.delete(post)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        user.bio = request.form.get('bio')

        if 'profile_pic' in request.files:
            p_file = request.files['profile_pic']
            if p_file and p_file.filename != '':
                p_res = cloudinary.uploader.upload(p_file)
                user.profile_pic = p_res.get('secure_url')

        if 'background_pic' in request.files:
            bg_file = request.files['background_pic']
            if bg_file and bg_file.filename != '':
                bg_res = cloudinary.uploader.upload(bg_file)
                user.background_pic = bg_res.get('secure_url')

        try:
            db.session.commit()
            # Kani nga line ang gi-update:
            return redirect(url_for('user_profile', username=user.username))
        except Exception as e:
            db.session.rollback()
            return f"Naay error sa pag-save: {str(e)}"

    return render_template('profile_settings.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('public_home'))

@app.route('/user/<username>')
def user_profile(username):
    target_user = User.query.filter_by(username=username).first_or_404()
    user_posts = Post.query.filter_by(author=username, approved=True).order_by(Post.created_at.desc()).all()
    logged_in_user = db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    return render_template('profile.html', target_user=target_user, posts=user_posts, user=logged_in_user)

@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):                                   
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    user_id = session['user_id']
    existing_like = Like.query.filter_by(user_id=user_id, post_id=post_id).first()                                  
    if existing_like:
        db.session.delete(existing_like)                      
        db.session.commit()
        return {"liked": False, "count": Like.query.filter_by(post_id=post_id).count()}
    else:
        new_like = Like(user_id=user_id, post_id=post_id)
        db.session.add(new_like)                              
        db.session.commit()
        return {"liked": True, "count": Like.query.filter_by(post_id=post_id).count()}                     

@app.route('/comment/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    
    user = db.session.get(User, session['user_id'])
    data = request.get_json()
    content = data.get('content', '').strip()
    
    if not content:
        return {"error": "Empty comment"}, 400
    
    new_comment = Comment(post_id=post_id, user_id=user.id, content=content)
    db.session.add(new_comment)
    db.session.commit()
    
    # Atong i-return ang formatted time (e.g., "Jan 16, 10:05 AM")
    formatted_time = new_comment.created_at.strftime('%b %d, %I:%M %p')
    
    return {
        "success": True,
        "username": user.username,
        "profile_pic": user.profile_pic if user.profile_pic else f"https://ui-avatars.com/api/?name={user.username}",
        "content": content,
        "created_at": formatted_time  # Gi-dugang ni nga field
    }

@app.route('/follow/<int:user_id>', methods=['POST'])
def follow_user(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    current_user_id = session['user_id']
    if current_user_id == user_id:
        return jsonify({'error': 'cannot follow yourself'}), 400
    existing_follow = Follow.query.filter_by(follower_id=current_user_id, followed_id=user_id).first()      
    if existing_follow:                                       
        db.session.delete(existing_follow)
        db.session.commit()
        return jsonify({'status': 'unfollowed', 'count': get_follower_count(user_id)})
    else:
        new_follow = Follow(follower_id=current_user_id, followed_id=user_id)
        db.session.add(new_follow)
        db.session.commit()
        return jsonify({'status': 'followed', 'count': get_follower_count(user_id)})

def get_follower_count(user_id):                          
    return Follow.query.filter_by(followed_id=user_id).count()

def is_following(follower_id, followed_id):
    return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None

app.jinja_env.globals.update(is_following=is_following, get_follower_count=get_follower_count)              

@app.route('/post/<slug>')
def view_post(slug):  # <--- Kinahanglan "view_post" ni nga name
    post = Post.query.filter_by(slug=slug).first_or_404()
    return render_template('view_post.html', post=post)

@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
    
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return {"error": "Comment not found"}, 404
        
    # Siguroon nga ang tag-iya sa comment ang nag-delete
    if comment.user_id != session['user_id']:
        return {"error": "Permission denied"}, 403
        
    db.session.delete(comment)
    db.session.commit()
    return {"success": True}

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
