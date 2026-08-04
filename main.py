from flask import Flask, request, jsonify, session, render_template
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)

# SECRET_KEYی جێگیر بۆ کارکردنی session لەسەر هەموو جێگایەک
app.secret_key = 'your-secret-key-here-change-in-production'  # لە بەرهەمهێناندا بە شێوەیەکی پارێزراو بگۆڕە

# ڕێکخستنی session بۆ کارکردن لە نێوان دۆمەینەکاندا
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True  # پێویستە لەسەر HTTPS

# ڕێگەدان بە CORS بۆ دۆمەینی فرانت (وەک خۆت)
CORS(app, supports_credentials=True, origins=["https://prices-form-production.up.railway.app", "http://localhost:5000", "https://your-frontend-domain.com"])

# DB_PATH دەبێت ئاماژە بکات بۆ فۆڵدەرێکی Volume-ی پارێزراو لە Railway
# (نەک فۆڵدەری کۆدەکە خۆی، چونکە ئەوە لەگەڵ هەر redeploy-ێک پاک دەکرێتەوە)
DB_PATH = os.environ.get('DB_PATH', 'database.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
    if data['username'] == 'admin' and data['password'] == 'admin123':
        session['admin'] = True
        session.modified = True
        return jsonify({'success': True, 'message': 'بەخێربێی بەڕێوەبەر'})
    return jsonify({'success': False, 'message': 'ناوی بەکارهێنەر یان وشەی تێپەڕ هەڵەیە'})

@app.route('/api/admin/data', methods=['GET'])
def admin_data():
    # پشکنینی بوونی admin لە session
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
    
    # تۆمارکردنی ژمارەی پڕۆداکتەکان لە کۆنسۆڵی سێرڤەر بۆ پشکنین
    print(f"Admin data: {len(result)} products found.")
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

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)