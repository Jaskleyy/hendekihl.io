from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
import os

# Resimlerin yüklenmesi için 'static' klasörünü Flask'a tanıtıyoruz
app = Flask(__name__, static_folder='static')

# Veritabanı dosyasının tam yolunu belirliyoruz (instance klasörü)
os.makedirs(app.instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'eco_access.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'erasmus2026-key'

db = SQLAlchemy(app)

# Kullanıcı Modeli
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    birth_date = db.Column(db.String(10), nullable=True)
    education_level = db.Column(db.String(30), nullable=True)
    carbon_score = db.Column(db.Float, default=0.0)


def ensure_user_columns():
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("user")}
    alter_statements = []

    if "full_name" not in existing_columns:
        alter_statements.append("ALTER TABLE user ADD COLUMN full_name VARCHAR(120)")
    if "birth_date" not in existing_columns:
        alter_statements.append("ALTER TABLE user ADD COLUMN birth_date VARCHAR(10)")
    if "education_level" not in existing_columns:
        alter_statements.append("ALTER TABLE user ADD COLUMN education_level VARCHAR(30)")

    for sql in alter_statements:
        db.session.execute(text(sql))
    if alter_statements:
        db.session.commit()

# KRİTİK NOKTA: Veritabanını sadece yoksa oluşturur, varsa verileri korur
with app.app_context():
    db.create_all()
    ensure_user_columns()

# --- Yönlendirmeler ---

@app.route('/')
def home():
    return send_from_directory('.', 'login.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('.', 'hesaplama.html')

# --- API İşlemleri ---

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    required_fields = ["username", "password", "full_name", "birth_date", "education_level"]
    if not data or any(not data.get(field) for field in required_fields):
        return jsonify({"message": "Eksik bilgi!"}), 400

    valid_levels = {"ilkokul", "ortaokul", "lise", "lisans", "yuksek_lisans"}
    if data["education_level"] not in valid_levels:
        return jsonify({"message": "Gecersiz okul duzeyi!"}), 400
        
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"message": "Kullanıcı adı sistemde mevcut!"}), 400
    
    new_user = User(
        username=data["username"],
        password=data["password"],
        full_name=data["full_name"],
        birth_date=data["birth_date"],
        education_level=data["education_level"],
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "Kayıt başarılı!"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and user.password == data['password']:
        return jsonify({"message": "Giriş başarılı!", "username": user.username}), 200
    return jsonify({"message": "Kullanıcı adı veya şifre hatalı!"}), 401

@app.route('/save_score', methods=['POST'])
def save_score():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user:
        user.carbon_score = data['score']
        db.session.commit()
        return jsonify({"message": "Skor kaydedildi!"}), 200
    return jsonify({"message": "Kullanıcı bulunamadı!"}), 404

if __name__ == '__main__':
    # Debug modu açık, dosya değişimlerinde kendi kendine yenilenir
if __name__ == '__main__':
    # Render portu dinamik olarak atar, bulamazsa 5000 kullanır
    port = int(os.environ.get("PORT", 5000))
    # host='0.0.0.0' dış dünyaya açılmak için kritiktir
    app.run(host='0.0.0.0', port=port)
