"""
帆船交流平台 - 后端主程序
Sailing Community Platform - Flask Backend
"""

import os
import json
import uuid
import time
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template, redirect, url_for, session
)
from flask_cors import CORS
from werkzeug.utils import secure_filename
from PIL import Image

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
CORS(app)

# 配置
UPLOAD_FOLDER_IMAGES = os.path.join('static', 'uploads', 'images')
UPLOAD_FOLDER_VIDEOS = os.path.join('static', 'uploads', 'videos')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi'}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB

os.makedirs(UPLOAD_FOLDER_IMAGES, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_VIDEOS, exist_ok=True)

# 数据存储文件
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, 'users.json')
POSTS_FILE = os.path.join(DATA_DIR, 'posts.json')
COMMENTS_FILE = os.path.join(DATA_DIR, 'comments.json')


# ============ 数据操作工具 ============

def load_data(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_data(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_id():
    return str(uuid.uuid4())[:8]


def allowed_file(filename, allowed_ext):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_ext


def time_ago(timestamp):
    """将时间戳转换为友好时间"""
    now = time.time()
    diff = now - timestamp
    if diff < 60:
        return '刚刚'
    elif diff < 3600:
        return f'{int(diff // 60)}分钟前'
    elif diff < 86400:
        return f'{int(diff // 3600)}小时前'
    elif diff < 2592000:
        return f'{int(diff // 86400)}天前'
    else:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d')


# ============ 登录检查 ============

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ============ 页面路由 ============

@app.route('/')
def index():
    return render_template('index.html')


# ============ 用户 API ============

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    nickname = data.get('nickname', '').strip() or username

    if not username or not password:
        return jsonify({'success': False, 'message': '用户名和密码不能为空'})
    if len(username) < 2 or len(username) > 20:
        return jsonify({'success': False, 'message': '用户名长度2-20个字符'})
    if len(password) < 4:
        return jsonify({'success': False, 'message': '密码至少4个字符'})

    users = load_data(USERS_FILE)
    if any(u['username'] == username for u in users):
        return jsonify({'success': False, 'message': '用户名已存在'})

    user = {
        'id': generate_id(),
        'username': username,
        'password': password,  # 简易版，生产环境应加密
        'nickname': nickname,
        'avatar': '',
        'bio': '热爱帆船运动',
        'created_at': time.time()
    }
    users.append(user)
    save_data(USERS_FILE, users)

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['nickname'] = user['nickname']

    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user['avatar'],
            'bio': user['bio']
        }
    })


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    users = load_data(USERS_FILE)
    user = next((u for u in users if u['username'] == username and u['password'] == password), None)
    if not user:
        return jsonify({'success': False, 'message': '用户名或密码错误'})

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['nickname'] = user['nickname']

    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', '')
        }
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/current_user', methods=['GET'])
def current_user():
    if 'user_id' not in session:
        return jsonify({'success': False, 'user': None})

    users = load_data(USERS_FILE)
    user = next((u for u in users if u['id'] == session['user_id']), None)
    if not user:
        session.clear()
        return jsonify({'success': False, 'user': None})

    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', '')
        }
    })


@app.route('/api/user/<user_id>', methods=['GET'])
def get_user(user_id):
    users = load_data(USERS_FILE)
    user = next((u for u in users if u['id'] == user_id), None)
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})

    posts = load_data(POSTS_FILE)
    user_posts = [p for p in posts if p['user_id'] == user_id]

    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', ''),
            'post_count': len(user_posts),
            'joined': time_ago(user['created_at'])
        }
    })


@app.route('/api/user/profile', methods=['PUT'])
@login_required
def update_profile():
    data = request.get_json()
    users = load_data(USERS_FILE)
    user = next((u for u in users if u['id'] == session['user_id']), None)
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'})

    if 'nickname' in data:
        user['nickname'] = data['nickname'].strip() or user['username']
        session['nickname'] = user['nickname']
    if 'bio' in data:
        user['bio'] = data['bio'].strip()

    save_data(USERS_FILE, users)
    return jsonify({'success': True, 'user': {
        'id': user['id'], 'username': user['username'],
        'nickname': user['nickname'], 'avatar': user.get('avatar', ''),
        'bio': user['bio']
    }})


# ============ 帖子 API ============

@app.route('/api/posts', methods=['GET'])
def get_posts():
    posts = load_data(POSTS_FILE)
    users = load_data(USERS_FILE)
    comments = load_data(COMMENTS_FILE)

    tag = request.args.get('tag', '').strip()
    keyword = request.args.get('keyword', '').strip()
    user_id = request.args.get('user_id', '').strip()
    sort = request.args.get('sort', 'latest')  # latest | hot

    if tag:
        posts = [p for p in posts if tag in p.get('tags', [])]
    if keyword:
        posts = [p for p in posts if keyword.lower() in p['title'].lower() or keyword.lower() in p['content'].lower()]
    if user_id:
        posts = [p for p in posts if p['user_id'] == user_id]

    # 排序
    if sort == 'hot':
        posts.sort(key=lambda p: p.get('likes', 0), reverse=True)
    else:
        posts.sort(key=lambda p: p['created_at'], reverse=True)

    # 附加用户信息和评论数
    user_map = {u['id']: u for u in users}
    result = []
    for p in posts:
        author = user_map.get(p['user_id'], {})
        comment_count = len([c for c in comments if c['post_id'] == p['id']])
        result.append({
            'id': p['id'],
            'title': p['title'],
            'content': p['content'],
            'images': p.get('images', []),
            'videos': p.get('videos', []),
            'tags': p.get('tags', []),
            'likes': p.get('likes', 0),
            'views': p.get('views', 0),
            'comment_count': comment_count,
            'created_at': p['created_at'],
            'time_ago': time_ago(p['created_at']),
            'author': {
                'id': author.get('id', ''),
                'nickname': author.get('nickname', '匿名'),
                'avatar': author.get('avatar', '')
            }
        })

    return jsonify({'success': True, 'posts': result})


@app.route('/api/posts', methods=['POST'])
@login_required
def create_post():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    tags_str = request.form.get('tags', '').strip()

    if not title:
        return jsonify({'success': False, 'message': '标题不能为空'})
    if not content:
        return jsonify({'success': False, 'message': '内容不能为空'})

    tags = [t.strip() for t in tags_str.split(',') if t.strip()] if tags_str else []

    # 处理图片上传
    images = []
    image_files = request.files.getlist('images')
    for img_file in image_files[:9]:  # 最多9张图
        if img_file and allowed_file(img_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            # 检查大小
            img_file.seek(0, 2)
            size = img_file.tell()
            img_file.seek(0)
            if size > MAX_IMAGE_SIZE:
                continue

            ext = img_file.filename.rsplit('.', 1)[1].lower()
            filename = f"{generate_id()}_{int(time.time())}.{ext}"
            filepath = os.path.join(UPLOAD_FOLDER_IMAGES, filename)

            # 保存并压缩图片
            img = Image.open(img_file)
            # 限制最大宽度
            max_width = 1200
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            img.save(filepath, quality=85, optimize=True)

            images.append(f'/static/uploads/images/{filename}')

    # 处理视频上传
    videos = []
    video_files = request.files.getlist('videos')
    for vid_file in video_files[:3]:  # 最多3个视频
        if vid_file and allowed_file(vid_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            vid_file.seek(0, 2)
            size = vid_file.tell()
            vid_file.seek(0)
            if size > MAX_VIDEO_SIZE:
                continue

            ext = vid_file.filename.rsplit('.', 1)[1].lower()
            filename = f"{generate_id()}_{int(time.time())}.{ext}"
            filepath = os.path.join(UPLOAD_FOLDER_VIDEOS, filename)
            vid_file.save(filepath)
            videos.append(f'/static/uploads/videos/{filename}')

    post = {
        'id': generate_id(),
        'title': title,
        'content': content,
        'images': images,
        'videos': videos,
        'tags': tags,
        'likes': 0,
        'views': 0,
        'liked_by': [],
        'user_id': session['user_id'],
        'created_at': time.time()
    }

    posts = load_data(POSTS_FILE)
    posts.append(post)
    save_data(POSTS_FILE, posts)

    return jsonify({'success': True, 'post_id': post['id']})


@app.route('/api/posts/<post_id>', methods=['GET'])
def get_post(post_id):
    posts = load_data(POSTS_FILE)
    post = next((p for p in posts if p['id'] == post_id), None)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    # 增加浏览量
    post['views'] = post.get('views', 0) + 1
    save_data(POSTS_FILE, posts)

    users = load_data(USERS_FILE)
    comments = load_data(COMMENTS_FILE)
    user_map = {u['id']: u for u in users}

    author = user_map.get(post['user_id'], {})

    # 获取评论
    post_comments = [c for c in comments if c['post_id'] == post_id]
    post_comments.sort(key=lambda c: c['created_at'])

    comment_list = []
    for c in post_comments:
        c_author = user_map.get(c['user_id'], {})
        comment_list.append({
            'id': c['id'],
            'content': c['content'],
            'created_at': c['created_at'],
            'time_ago': time_ago(c['created_at']),
            'author': {
                'id': c_author.get('id', ''),
                'nickname': c_author.get('nickname', '匿名'),
                'avatar': c_author.get('avatar', '')
            }
        })

    # 检查当前用户是否已点赞
    is_liked = False
    if 'user_id' in session:
        is_liked = session['user_id'] in post.get('liked_by', [])

    return jsonify({
        'success': True,
        'post': {
            'id': post['id'],
            'title': post['title'],
            'content': post['content'],
            'images': post.get('images', []),
            'videos': post.get('videos', []),
            'tags': post.get('tags', []),
            'likes': post.get('likes', 0),
            'views': post.get('views', 0),
            'is_liked': is_liked,
            'comment_count': len(post_comments),
            'created_at': post['created_at'],
            'time_ago': time_ago(post['created_at']),
            'author': {
                'id': author.get('id', ''),
                'nickname': author.get('nickname', '匿名'),
                'avatar': author.get('avatar', '')
            },
            'comments': comment_list
        }
    })


@app.route('/api/posts/<post_id>', methods=['DELETE'])
@login_required
def delete_post(post_id):
    posts = load_data(POSTS_FILE)
    post = next((p for p in posts if p['id'] == post_id), None)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})
    if post['user_id'] != session['user_id']:
        return jsonify({'success': False, 'message': '无权删除'})

    # 删除关联文件
    for img in post.get('images', []):
        img_path = os.path.join(os.path.dirname(__file__), img.lstrip('/'))
        if os.path.exists(img_path):
            os.remove(img_path)
    for vid in post.get('videos', []):
        vid_path = os.path.join(os.path.dirname(__file__), vid.lstrip('/'))
        if os.path.exists(vid_path):
            os.remove(vid_path)

    posts = [p for p in posts if p['id'] != post_id]
    save_data(POSTS_FILE, posts)

    # 删除评论
    comments = load_data(COMMENTS_FILE)
    comments = [c for c in comments if c['post_id'] != post_id]
    save_data(COMMENTS_FILE, comments)

    return jsonify({'success': True})


# ============ 点赞 API ============

@app.route('/api/posts/<post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    posts = load_data(POSTS_FILE)
    post = next((p for p in posts if p['id'] == post_id), None)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    user_id = session['user_id']
    liked_by = post.get('liked_by', [])

    if user_id in liked_by:
        liked_by.remove(user_id)
        post['likes'] = max(0, post.get('likes', 1) - 1)
        liked = False
    else:
        liked_by.append(user_id)
        post['likes'] = post.get('likes', 0) + 1
        liked = True

    post['liked_by'] = liked_by
    save_data(POSTS_FILE, posts)

    return jsonify({'success': True, 'liked': liked, 'likes': post['likes']})


# ============ 评论 API ============

@app.route('/api/posts/<post_id>/comments', methods=['POST'])
@login_required
def add_comment(post_id):
    data = request.get_json()
    content = data.get('content', '').strip()

    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空'})

    posts = load_data(POSTS_FILE)
    post = next((p for p in posts if p['id'] == post_id), None)
    if not post:
        return jsonify({'success': False, 'message': '帖子不存在'})

    comment = {
        'id': generate_id(),
        'post_id': post_id,
        'user_id': session['user_id'],
        'content': content,
        'created_at': time.time()
    }

    comments = load_data(COMMENTS_FILE)
    comments.append(comment)
    save_data(COMMENTS_FILE, comments)

    users = load_data(USERS_FILE)
    user = next((u for u in users if u['id'] == session['user_id']), {})

    return jsonify({
        'success': True,
        'comment': {
            'id': comment['id'],
            'content': comment['content'],
            'time_ago': time_ago(comment['created_at']),
            'author': {
                'id': user.get('id', ''),
                'nickname': user.get('nickname', '匿名'),
                'avatar': user.get('avatar', '')
            }
        }
    })


# ============ 标签 API ============

@app.route('/api/tags', methods=['GET'])
def get_tags():
    posts = load_data(POSTS_FILE)
    tag_count = {}
    for p in posts:
        for tag in p.get('tags', []):
            tag_count[tag] = tag_count.get(tag, 0) + 1

    # 按数量排序
    tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)
    return jsonify({'success': True, 'tags': [{'name': t[0], 'count': t[1]} for t in tags]})


# ============ 统计 API ============

@app.route('/api/stats', methods=['GET'])
def get_stats():
    posts = load_data(POSTS_FILE)
    users = load_data(USERS_FILE)
    comments = load_data(COMMENTS_FILE)
    return jsonify({
        'success': True,
        'stats': {
            'posts': len(posts),
            'users': len(users),
            'comments': len(comments)
        }
    })


# ============ 启动 ============

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print('⛵ 帆船交流平台启动中...')
    print(f'📁 数据目录: {DATA_DIR}')
    print(f'🖼️  图片目录: {UPLOAD_FOLDER_IMAGES}')
    print(f'🎬 视频目录: {UPLOAD_FOLDER_VIDEOS}')
    print(f'🌐 监听端口: {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
