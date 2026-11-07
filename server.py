import os
import random
import string
from datetime import datetime
from flask import Flask, request, jsonify, session, send_from_directory

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'  # 请修改为随机字符串

# ================== 数据存储（内存） ==================
users = {}                # phone -> {phone, username, password}
rooms = {}                # room_code -> {code, name, password, owner_phone, members: set(), messages: [], join_requests: []}
user_rooms_created = {}   # phone -> [room_codes]  最多5个
user_rooms_joined = {}    # phone -> set(room_codes) 最多10个（含自己创建的）
join_request_counter = 1  # 用于生成请求ID

# ================== 辅助函数 ==================
def generate_room_code():
    """生成6位随机不重复数字"""
    while True:
        code = ''.join(random.choices(string.digits, k=6))
        if code not in rooms:
            return code

def get_current_user():
    """从session获取当前登录用户"""
    phone = session.get('phone')
    return users.get(phone)

def require_login(func):
    """装饰器：要求登录"""
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

def format_room(room_code):
    """返回房间的公开信息"""
    room = rooms.get(room_code)
    if not room:
        return None
    owner = users.get(room['owner_phone'])
    current = get_current_user()
    return {
        'code': room['code'],
        'name': room['name'],
        'owner': room['owner_phone'],
        'owner_name': owner['username'] if owner else '未知',
        'member_count': len(room['members']),
        'is_owner': bool(current and room['owner_phone'] == current['phone']),
        'is_member': bool(current and current['phone'] in room['members'])
    }

# ================== 首页路由 ==================
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ================== 认证接口 ==================
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    phone = data.get('phone', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not phone or not username or not password:
        return jsonify({'success': False, 'message': '所有字段均为必填'})

    if not phone.isdigit() or len(phone) != 11:
        return jsonify({'success': False, 'message': '请输入11位手机号'})

    if phone in users:
        return jsonify({'success': False, 'message': '该手机号已注册'})

    users[phone] = {
        'phone': phone,
        'username': username,
        'password': password
    }
    user_rooms_created[phone] = []
    user_rooms_joined[phone] = set()
    return jsonify({'success': True, 'message': '注册成功'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    phone = data.get('phone', '').strip()
    password = data.get('password', '')

    user = users.get(phone)
    if not user or user['password'] != password:
        return jsonify({'success': False, 'message': '手机号或密码错误'})

    session['phone'] = phone
    return jsonify({'success': True, 'user': {'phone': phone, 'username': user['username']}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('phone', None)
    return jsonify({'success': True})

@app.route('/api/check_session', methods=['GET'])
def check_session():
    user = get_current_user()
    if user:
        return jsonify({'success': True, 'user': {'phone': user['phone'], 'username': user['username']}})
    return jsonify({'success': False})

# ================== 聊天室接口 ==================
@app.route('/api/rooms', methods=['GET'])
@require_login
def get_rooms():
    user = get_current_user()
    phone = user['phone']

    joined_rooms = []
    created_rooms = []

    for code in user_rooms_joined.get(phone, []):
        if code in rooms:
            joined_rooms.append(format_room(code))

    for code in user_rooms_created.get(phone, []):
        if code in rooms:
            created_rooms.append(format_room(code))

    return jsonify({
        'success': True,
        'rooms': joined_rooms,
        'created_rooms': created_rooms,
        'created_count': len(created_rooms),
        'joined_count': len(joined_rooms)
    })

@app.route('/api/create_room', methods=['POST'])
@require_login
def create_room():
    user = get_current_user()
    phone = user['phone']

    if len(user_rooms_created.get(phone, [])) >= 5:
        return jsonify({'success': False, 'message': '您最多只能创建5个聊天室'})

    data = request.json
    name = data.get('name', '').strip()
    password = data.get('password', '')

    if not name or not password:
        return jsonify({'success': False, 'message': '房间名称和密码不能为空'})

    if len(name) > 20:
        return jsonify({'success': False, 'message': '房间名称不能超过20字'})

    code = generate_room_code()
    rooms[code] = {
        'code': code,
        'name': name,
        'password': password,
        'owner_phone': phone,
        'members': {phone},
        'messages': [],
        'join_requests': []
    }

    user_rooms_created[phone].append(code)
    user_rooms_joined[phone].add(code)

    return jsonify({'success': True, 'room_code': code, 'message': '创建成功'})

@app.route('/api/search_room', methods=['GET'])
@require_login
def search_room():
    code = request.args.get('code', '').strip()
    if not code or len(code) != 6 or not code.isdigit():
        return jsonify({'success': False, 'message': '请输入6位数字房间号'})

    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    return jsonify({'success': True, 'room': format_room(code)})

@app.route('/api/join_room', methods=['POST'])
@require_login
def join_room():
    user = get_current_user()
    phone = user['phone']

    data = request.json
    code = data.get('code')
    password = data.get('password', '')

    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    if phone in room['members']:
        return jsonify({'success': False, 'message': '你已在该聊天室中'})

    if len(user_rooms_joined.get(phone, set())) >= 10:
        return jsonify({'success': False, 'message': '您最多只能加入10个聊天室'})

    if room['password'] != password:
        return jsonify({'success': False, 'message': '密码错误', 'need_password': True})

    global join_request_counter
    request_id = join_request_counter
    join_request_counter += 1

    for req in room['join_requests']:
        if req['phone'] == phone and req['status'] == 'pending':
            return jsonify({'success': False, 'message': '你已有待处理的加入请求'})

    new_req = {
        'id': request_id,
        'phone': phone,
        'username': user['username'],
        'status': 'pending'
    }
    room['join_requests'].append(new_req)

    if room['owner_phone'] == phone:
        new_req['status'] = 'approved'
        room['members'].add(phone)
        user_rooms_joined[phone].add(code)
        return jsonify({'success': True, 'status': 'approved'})

    return jsonify({'success': True, 'status': 'pending', 'request_id': request_id})

@app.route('/api/check_join_request', methods=['GET'])
@require_login
def check_join_request():
    request_id = request.args.get('request_id')
    if not request_id:
        return jsonify({'success': False})

    try:
        request_id = int(request_id)
    except:
        return jsonify({'success': False})

    for room in rooms.values():
        for req in room['join_requests']:
            if req['id'] == request_id:
                return jsonify({
                    'success': True,
                    'status': req['status'],
                    'room_code': room['code']
                })
    return jsonify({'success': False})

@app.route('/api/room/<code>/info', methods=['GET'])
@require_login
def room_info(code):
    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    user = get_current_user()
    phone = user['phone']

    if phone not in room['members'] and room['owner_phone'] != phone:
        return jsonify({'success': False, 'message': '你不是该房间成员'})

    return jsonify({
        'success': True,
        'room': {
            'code': room['code'],
            'name': room['name'],
            'owner_phone': room['owner_phone'],
            'is_owner': room['owner_phone'] == phone,
            'member_count': len(room['members'])
        }
    })

@app.route('/api/room/<code>/messages', methods=['GET'])
@require_login
def get_messages(code):
    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    user = get_current_user()
    if user['phone'] not in room['members']:
        return jsonify({'success': False, 'message': '你不是该房间成员'})

    messages = []
    for msg in room['messages']:
        sender = users.get(msg['sender'], {})
        messages.append({
            'sender': msg['sender'],
            'username': sender.get('username', '未知'),
            'content': msg['content'],
            'timestamp': msg['timestamp']
        })

    return jsonify({'success': True, 'messages': messages})

@app.route('/api/room/<code>/send', methods=['POST'])
@require_login
def send_message(code):
    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    user = get_current_user()
    if user['phone'] not in room['members']:
        return jsonify({'success': False, 'message': '你不是该房间成员'})

    data = request.json
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'message': '消息不能为空'})

    room['messages'].append({
        'sender': user['phone'],
        'content': content,
        'timestamp': datetime.now().strftime('%H:%M:%S')
    })
    return jsonify({'success': True})

@app.route('/api/room/<code>/requests', methods=['GET'])
@require_login
def get_join_requests(code):
    room = rooms.get(code)
    if not room:
        return jsonify({'success': False, 'message': '房间不存在'})

    user = get_current_user()
    if room['owner_phone'] != user['phone']:
        return jsonify({'success': False, 'message': '只有房主可以查看请求'})

    return jsonify({'success': True, 'requests': room['join_requests']})

@app.route('/api/respond_join_request', methods=['POST'])
@require_login
def respond_join_request():
    user = get_current_user()
    data = request.json
    request_id = data.get('request_id')
    status = data.get('status')

    if status not in ['approved', 'rejected']:
        return jsonify({'success': False, 'message': '无效状态'})

    for room in rooms.values():
        if room['owner_phone'] != user['phone']:
            continue
        for req in room['join_requests']:
            if req['id'] == request_id and req['status'] == 'pending':
                req['status'] = status
                if status == 'approved':
                    room['members'].add(req['phone'])
                    user_rooms_joined.setdefault(req['phone'], set()).add(room['code'])
                return jsonify({'success': True, 'message': '操作成功'})

    return jsonify({'success': False, 'message': '请求不存在或已处理'})

# ================== 启动服务器 ==================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"✅ 暖聊服务器启动中... 端口: {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)