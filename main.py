from flask import Flask, request, jsonify, session, render_template
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3
import os

app = Flask(__name__)

# Railway لەپشتی proxy کار دەکات؛ بێ ئەمە Flask بە هەڵە بڕیار دەدات کە داواکارییەکە HTTPS نییە
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# SECRET_KEYی جێگیر بۆ کارکردنی session لەسەر هەموو جێگایەک
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')

# ڕێکخستنی session بۆ کارکردن لە نێوان دۆمەینەکاندا
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True  # پێویستە لەسەر HTTPS

# ==============================================================
# گرنگ: شوێنی داتابەیس - پێویستە لەسەر Railway Volume بێت
# ==============================================================
# بێ Volume، Railway هەر جارێک redeploy یان restart بکات، هەموو
# فایلەکانی نوێ (لەوانە database.db) دەسڕێتەوە چونکە دیسکەکە
# سەردەمە (ephemeral). بۆیە:
# 1. لە Railway dashboard دا Volume زیاد بکە (Settings > Volumes)
# 2. Mount path بکە بە شێوەی: /data
# 3. Environment Variable زیاد بکە: DB_PATH=/data/database.db
DB_PATH = os.environ.get('DB_PATH', 'database.db')

# ڕێگەدان بە CORS بۆ دۆمەینی فرانت
# گرنگ: ئەگەر فرانت و باکەند لە یەک دۆمەین/Railway app نین،
# دۆمەینی ڕاستەقینەی فرانتەندەکەت لێرە زیاد بکە (بەجێی placeholder ـەکان)
ALLOWED_ORIGINS = os.environ.get(
    'ALLOWED_ORIGINS',
    'https://prices-form-production.up.railway.app,http://localhost:5000'
).split(',')

CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # دڵنیابوون لەوەی فۆڵدەری داتابەیسەکە بوونی هەیە (بۆ نموونە ئەگەر /data/database.db بێت)
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            location TEXT,
            password TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            qty INTEGER DEFAULT 1,
            total REAL,
            image TEXT,
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        )
    ''')
    conn.commit()
    conn.close()
init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db()
    try:
        conn.execute('INSERT INTO shops (name, phone, location, password) VALUES (?, ?, ?, ?)',
                     (data['name'], data['phone'], data['location'], data['password']))
        conn.commit()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'ئەم ژمارە پێشتر تۆمارکراوە'})
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    user = conn.execute('SELECT * FROM shops WHERE phone = ? AND password = ?',
                        (data['phone'], data['password'])).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session.permanent = True
        return jsonify({
            'success': True,
            'seller': {
                'id': user['id'],
                'name': user['name'],
                'phone': user['phone'],
                'location': user['location']
            }
        })
    return jsonify({'success': False, 'message': 'ژمارە یان وشەی تێپەڕ هەڵەیە'})

@app.route('/api/products', methods=['POST'])
def add_products():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'تکایە بچۆ ژوورەوە'})
    data = request.json
    shop_id = session['user_id']
    conn = get_db()
    for p in data['products']:
        conn.execute('INSERT INTO products (shop_id, name, category, price, qty, total, image) VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (shop_id, p['name'], p['category'], p['price'],
                      p.get('qty', 1), p.get('total', p['price'] * p.get('qty', 1)), p['image']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
    if data['username'] == admin_user and data['password'] == admin_pass:
        session['admin'] = True
        session.permanent = True
        session.modified = True
        return jsonify({'success': True, 'message': 'بەخێربێی بەڕێوەبەر'})
    return jsonify({'success': False, 'message': 'ناوی بەکارهێنەر یان وشەی تێپەڕ هەڵەیە'})

@app.route('/api/admin/data', methods=['GET'])
def admin_data():
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'دەستپێگەیشتن ڕەتکراوە - تکایە دوبارە بچۆ ژوورەوە وەک بەڕێوەبەر'})

    conn = get_db()
    products = conn.execute('''
        SELECT
            p.id,
            p.name,
            p.category,
            p.price,
            p.qty,
            p.total,
            p.image,
            s.name as shop_name,
            s.phone,
            s.location
        FROM products p
        JOIN shops s ON p.shop_id = s.id
        ORDER BY p.id DESC
    ''').fetchall()
    conn.close()

    result = []
    for row in products:
        result.append({
            'id': row['id'],
            'name': row['name'],
            'category': row['category'],
            'price': row['price'],
            'qty': row['qty'],
            'total': row['total'],
            'image': row['image'],
            'shop_name': row['shop_name'],
            'phone': row['phone'],
            'location': row['location']
        })

    print(f"Admin data: {len(result)} products found. DB_PATH={DB_PATH}")
    return jsonify({
        'success': True,
        'products': result
    })

@app.route('/api/admin/product/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    if not session.get('admin'):
        return jsonify({'success': False, 'message': 'دەستپێگەیشتن ڕەتکراوە'})
    conn = get_db()
    conn.execute('DELETE FROM products WHERE id = ?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/session', methods=['GET'])
def get_session():
    if session.get('admin'):
        return jsonify({'logged_in': True, 'is_admin': True})
    if 'user_id' in session:
        conn = get_db()
        user = conn.execute('SELECT id, name, phone, location FROM shops WHERE id = ?',
                            (session['user_id'],)).fetchone()
        conn.close()
        if user:
            return jsonify({'logged_in': True, 'seller': dict(user)})
    return jsonify({'logged_in': False})

@app.route('/api/debug/dbinfo', methods=['GET'])
def debug_dbinfo():
    """کاریگەری کاتی: بۆ پشکنینی شوێن و بارودۆخی داتابەیس لە پرۆدەکشندا.
    دەتوانیت دوای دڵنیابوونەوە لە چارەسەرکردنی کێشەکە ئەم route ـە بسڕیتەوە."""
    conn = get_db()
    shops_count = conn.execute('SELECT COUNT(*) c FROM shops').fetchone()['c']
    products_count = conn.execute('SELECT COUNT(*) c FROM products').fetchone()['c']
    conn.close()
    return jsonify({
        'db_path': DB_PATH,
        'db_path_absolute': os.path.abspath(DB_PATH),
        'db_exists': os.path.exists(DB_PATH),
        'shops_count': shops_count,
        'products_count': products_count
    })

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
