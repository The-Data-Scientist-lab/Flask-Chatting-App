from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your-secret-key'
socketio = SocketIO(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# File upload config
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'mp4', 'mov'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# SQLite Database Setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, 
        username TEXT UNIQUE, 
        password TEXT, 
        online INTEGER DEFAULT 0,
        profile_pic TEXT DEFAULT 'default.png',
        bio TEXT DEFAULT 'Hey there!'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY, 
        user_id INTEGER, 
        friend_id INTEGER, 
        status TEXT DEFAULT 'pending', 
        FOREIGN KEY(user_id) REFERENCES users(id), 
        FOREIGN KEY(friend_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY, 
        sender_id INTEGER, 
        receiver_id INTEGER, 
        message TEXT, 
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        read INTEGER DEFAULT 0,
        FOREIGN KEY(sender_id) REFERENCES users(id), 
        FOREIGN KEY(receiver_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        content TEXT,
        media TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()

init_db()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1])
    return None

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        if user and user[2] == password:
            login_user(User(user[0], user[1]))
            c.execute('UPDATE users SET online = 1 WHERE id = ?', (user[0],))
            conn.commit()
            socketio.emit('status_update', {'username': username, 'online': True})
            socketio.emit('activity', {'message': f"{username} came online", 'timestamp': datetime.now().strftime('%H:%M')})
        conn.close()
        if user:
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        try:
            c.execute('INSERT INTO users (username, password, online) VALUES (?, ?, 0)', (username, password))
            conn.commit()
            flash('Registration successful! Please log in.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already taken')
        conn.close()
    return render_template('register.html')

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    if request.method == 'POST':
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                c.execute('UPDATE users SET profile_pic = ? WHERE id = ?', (filename, current_user.id))
        elif 'bio' in request.form:
            bio = request.form['bio']
            c.execute('UPDATE users SET bio = ? WHERE id = ?', (bio, current_user.id))
        conn.commit()
    c.execute('SELECT profile_pic, bio FROM users WHERE id = ?', (current_user.id,))
    user_data = c.fetchone()
    profile_pic, bio = user_data[0], user_data[1]
    c.execute('''SELECT u.username, u.online FROM users u 
                 JOIN friends f ON u.id = f.friend_id 
                 WHERE f.user_id = ? AND f.status = 'accepted' ''', (current_user.id,))
    friends = [{'username': row[0], 'online': bool(row[1])} for row in c.fetchall()]
    c.execute('''SELECT u.username FROM users u 
                 JOIN friends f ON u.id = f.user_id 
                 WHERE f.friend_id = ? AND f.status = 'pending' ''', (current_user.id,))
    requests = [row[0] for row in c.fetchall()]
    c.execute('''SELECT u.username, m.message, m.timestamp, m.read
                 FROM messages m
                 JOIN users u ON u.id = CASE WHEN m.sender_id = ? THEN m.receiver_id ELSE m.sender_id END
                 WHERE (m.sender_id = ? OR m.receiver_id = ?)
                 GROUP BY u.id
                 ORDER BY m.timestamp DESC LIMIT 5''', (current_user.id, current_user.id, current_user.id))
    recent_chats = [{'username': row[0], 'message': row[1], 'timestamp': row[2], 'read': bool(row[3])} for row in c.fetchall()]
    c.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND read = 0', (current_user.id,))
    unread_count = c.fetchone()[0]
    conn.close()
    return render_template('dashboard.html', username=current_user.username, profile_pic=profile_pic, bio=bio, friends=friends, requests=requests, recent_chats=recent_chats, unread_count=unread_count)

@app.route('/profile/<username>')
@login_required
def profile(username):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, profile_pic, bio, online FROM users WHERE username = ?', (username,))
    user_data = c.fetchone()
    if not user_data:
        flash('User not found')
        return redirect(url_for('dashboard'))
    user_id, profile_pic, bio, online = user_data
    c.execute('SELECT * FROM friends WHERE user_id = ? AND friend_id = ? AND status = "accepted"', (current_user.id, user_id))
    is_friend = bool(c.fetchone())
    if not is_friend and username != current_user.username:
        flash('You can only view profiles of your friends')
        return redirect(url_for('dashboard'))
    c.execute('SELECT u.username FROM users u JOIN friends f ON u.id = f.user_id WHERE f.friend_id = ? AND f.status = "accepted"', (user_id,))
    followers = [row[0] for row in c.fetchall()]
    c.execute('SELECT u.username FROM users u JOIN friends f ON u.id = f.friend_id WHERE f.user_id = ? AND f.status = "accepted"', (user_id,))
    following = [row[0] for row in c.fetchall()]
    c.execute('SELECT content, media, timestamp FROM posts WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10', (user_id,))
    posts = [{'content': row[0], 'media': row[1], 'timestamp': row[2]} for row in c.fetchall()]
    conn.close()
    return render_template('profile.html', profile_username=username, profile_pic=profile_pic, bio=bio, online=online, followers=followers, following=following, posts=posts, is_friend=is_friend)

@app.route('/search_users', methods=['GET'])
@login_required
def search_users():
    query = request.args.get('q', '')
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT username FROM users WHERE username LIKE ? AND username != ?',
              (f'%{query}%', current_user.username))
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return jsonify(users)

@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    friend_username = request.form['friend']
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (friend_username,))
    friend = c.fetchone()
    if friend:
        c.execute('SELECT * FROM friends WHERE user_id = ? AND friend_id = ?', (current_user.id, friend[0]))
        if not c.fetchone():
            c.execute('INSERT INTO friends (user_id, friend_id) VALUES (?, ?)', (current_user.id, friend[0]))
            conn.commit()
            socketio.emit('friend_notification', {'type': 'request_sent', 'from': current_user.username, 'to': friend_username}, room=friend_username)
            socketio.emit('friend_notification', {'type': 'request_received', 'from': friend_username, 'to': current_user.username}, room=current_user.username)
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/accept_friend', methods=['POST'])
@login_required
def accept_friend():
    friend_username = request.form['friend']
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (friend_username,))
    friend = c.fetchone()
    if friend:
        c.execute('UPDATE friends SET status = "accepted" WHERE user_id = ? AND friend_id = ?', (friend[0], current_user.id))
        c.execute('INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?, ?, "accepted")',
                  (current_user.id, friend[0]))
        conn.commit()
        socketio.emit('activity', {'message': f"{current_user.username} accepted {friend_username}'s friend request", 'timestamp': datetime.now().strftime('%H:%M')})
        socketio.emit('friend_notification', {'type': 'request_accepted', 'from': current_user.username, 'to': friend_username}, room=friend_username)
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/chat/<friend>')
@login_required
def chat(friend):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (friend,))
    friend_id = c.fetchone()
    if not friend_id:
        flash('Friend not found')
        return redirect(url_for('dashboard'))
    friend_id = friend_id[0]
    c.execute('''SELECT sender_id, message FROM messages 
                 WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) 
                 ORDER BY timestamp''', (current_user.id, friend_id, friend_id, current_user.id))
    messages = [{'sender': current_user.username if row[0] == current_user.id else friend, 'message': row[1]}
                for row in c.fetchall()]
    c.execute('UPDATE messages SET read = 1 WHERE receiver_id = ? AND sender_id = ?', (current_user.id, friend_id))
    c.execute('SELECT profile_pic, online FROM users WHERE id = ?', (friend_id,))
    friend_data = c.fetchone()
    friend_profile_pic, friend_online = friend_data[0], bool(friend_data[1])
    c.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND read = 0', (current_user.id,))
    unread_count = c.fetchone()[0]
    conn.commit()
    conn.close()
    return render_template('chat.html', username=current_user.username, friend=friend, messages=messages, friend_profile_pic=friend_profile_pic, friend_online=friend_online, unread_count=unread_count)

@app.route('/post', methods=['GET', 'POST'])
@login_required
def post():
    if request.method == 'POST':
        content = request.form.get('content', '')
        media = request.files.get('media')
        media_filename = None
        if media and allowed_file(media.filename):
            media_filename = secure_filename(media.filename)
            media.save(os.path.join(app.config['UPLOAD_FOLDER'], media_filename))
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('INSERT INTO posts (user_id, content, media) VALUES (?, ?, ?)',
                  (current_user.id, content, media_filename))
        conn.commit()
        conn.close()
        return redirect(url_for('dashboard'))
    return render_template('post.html')

@app.route('/logout')
@login_required
def logout():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET online = 0 WHERE id = ?', (current_user.id,))
    conn.commit()
    socketio.emit('status_update', {'username': current_user.username, 'online': False})
    socketio.emit('activity', {'message': f"{current_user.username} went offline", 'timestamp': datetime.now().strftime('%H:%M')})
    conn.close()
    logout_user()
    return redirect(url_for('login'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# SocketIO Events
@socketio.on('connect')
def on_connect():
    join_room(current_user.username)
    emit('status_update', {'username': current_user.username, 'online': True})
    emit('activity', {'message': f"{current_user.username} came online", 'timestamp': datetime.now().strftime('%H:%M')})

@socketio.on('disconnect')
def on_disconnect():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE users SET online = 0 WHERE id = ?', (current_user.id,))
    conn.commit()
    conn.close()
    leave_room(current_user.username)
    emit('status_update', {'username': current_user.username, 'online': False})
    emit('activity', {'message': f"{current_user.username} went offline", 'timestamp': datetime.now().strftime('%H:%M')})

@socketio.on('join')
def on_join(data):
    username = data['username']
    join_room(username)

@socketio.on('message')
def handle_message(data):
    sender = current_user.username
    recipient = data['recipient']
    message = data['message']
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (recipient,))
    recipient_id = c.fetchone()[0]
    c.execute('INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)',
              (current_user.id, recipient_id, message))
    conn.commit()
    c.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND read = 0', (recipient_id,))
    unread_count = c.fetchone()[0]
    conn.close()
    emit('message', {'sender': sender, 'message': message}, room=sender)
    emit('message', {'sender': sender, 'message': message}, room=recipient)
    emit('new_message', {'sender': sender, 'message': message, 'unread_count': unread_count}, room=recipient)
    emit('update_recent_chats', {'username': sender, 'message': message, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'read': False}, room=recipient)
    emit('new_message_alert', {'sender': sender, 'message': message}, room=recipient)

@socketio.on('typing')
def handle_typing(data):
    recipient = data['recipient']
    typing = data['typing']
    emit('typing', {'user': current_user.username, 'typing': typing}, room=recipient)

if __name__ == '__main__':
    socketio.run(app, debug=True)