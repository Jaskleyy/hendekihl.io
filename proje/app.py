from datetime import date, datetime, timedelta
import json
import os
import re
import secrets
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

# Flask & Extensions
from flask import Flask, jsonify, redirect, request, send_from_directory, session, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text, func, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from openai import OpenAI

app = Flask(__name__, static_folder="static")

# --- AYARLAR (APPLE STANDARD) ---
os.makedirs(app.instance_path, exist_ok=True)
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
SOCIAL_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, "social")
os.makedirs(SOCIAL_UPLOAD_FOLDER, exist_ok=True)

# Veritabanı & Güvenlik
database_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "eco_access.db"))
if database_url.startswith("postgres://"):
    database_url = "postgresql://" + database_url[len("postgres://"):]
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gizli-anahtar-degistir")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024 # 16MB Upload limiti

# Geliştirmede restart gerekmemesi için template/static auto-reload.
DEV_HOT_RELOAD = os.environ.get("ECO_DEV_HOT_RELOAD", "1") == "1"
if DEV_HOT_RELOAD:
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.jinja_env.auto_reload = True

# --- MAIL AYARLARI (GMAIL ÖRNEĞİ) ---
# BURAYI KENDİ BİLGİLERİNLE DOLDURACAKSIN
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_EMAIL = "seninmailin@gmail.com"  # GÖNDERİCİ MAİLİ
SMTP_PASSWORD = "buraya_app_password_gelecek" # UYGULAMA ŞİFRESİ

# --- AI API (DEEPSEEK / OPENROUTER) ---
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat"
_ai_client = None
_ai_client_key = None
_ai_client_base_url = None


def get_ai_api_key():
    for env_name in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        key = (os.environ.get(env_name) or "").strip()
        if key:
            return key, env_name
    return "", None


def get_ai_model():
    model = (os.environ.get("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
    return model or DEFAULT_OPENROUTER_MODEL


def get_ai_client(force_refresh=False):
    global _ai_client, _ai_client_key, _ai_client_base_url

    api_key, key_name = get_ai_api_key()
    base_url = (os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_OPENROUTER_BASE_URL

    if not api_key:
        _ai_client = None
        _ai_client_key = None
        _ai_client_base_url = base_url
        return None

    needs_refresh = (
        force_refresh
        or _ai_client is None
        or _ai_client_key != api_key
        or _ai_client_base_url != base_url
    )
    if not needs_refresh:
        return _ai_client

    try:
        _ai_client = OpenAI(api_key=api_key, base_url=base_url)
        _ai_client_key = api_key
        _ai_client_base_url = base_url
        return _ai_client
    except Exception as exc:
        print(f"AI istemcisi baslatilamadi ({key_name or 'api_key_yok'}): {exc}")
        _ai_client = None
        _ai_client_key = None
        _ai_client_base_url = base_url
        return None

db = SQLAlchemy(app)
FORUM_CATEGORIES = {"genel", "ulasim", "enerji", "beslenme", "teknoloji", "yasam"}
EDUCATION_LEVELS = {"ilkokul", "ortaokul", "lise", "lisans", "yetiskin"}
LEGACY_EDUCATION_MAP = {"yuksek_lisans": "lisans"}
ALLOWED_SOCIAL_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_SOCIAL_GIF_EXTENSIONS = {"gif"}
ALLOWED_SOCIAL_FILE_EXTENSIONS = {"pdf", "txt", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx", "zip", "rar", "7z"}
POST_APPROVAL_PENDING = "pending"
POST_APPROVAL_APPROVED = "approved"
POST_APPROVAL_REJECTED = "rejected"
OWNER_USERNAME = (os.environ.get("ECO_OWNER_USERNAME") or "eymen").strip()
OWNER_PASSWORD = os.environ.get("ECO_OWNER_PASSWORD") or "eymen200909"
GIPHY_API_KEY = (os.environ.get("GIPHY_API_KEY") or "").strip()
GIPHY_API_BASE = "https://api.giphy.com/v1/gifs"
GIPHY_FALLBACK_ITEMS = [
    {"gif_id": "3o7aD2saalBwwftBIY", "title": "Sustainable Earth", "gif_url": "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif", "preview_url": "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif", "width": 480, "height": 270},
    {"gif_id": "26BRuo6sLetdllPAQ", "title": "Climate Action", "gif_url": "https://media.giphy.com/media/26BRuo6sLetdllPAQ/giphy.gif", "preview_url": "https://media.giphy.com/media/26BRuo6sLetdllPAQ/giphy.gif", "width": 480, "height": 270},
    {"gif_id": "3o6MbfSIP0BzoCN7nW", "title": "Green Planet", "gif_url": "https://media.giphy.com/media/3o6MbfSIP0BzoCN7nW/giphy.gif", "preview_url": "https://media.giphy.com/media/3o6MbfSIP0BzoCN7nW/giphy.gif", "width": 480, "height": 270},
    {"gif_id": "l0MYC0LajbaPoEADu", "title": "Recycling", "gif_url": "https://media.giphy.com/media/l0MYC0LajbaPoEADu/giphy.gif", "preview_url": "https://media.giphy.com/media/l0MYC0LajbaPoEADu/giphy.gif", "width": 480, "height": 270},
    {"gif_id": "3oEduSbSGpGaRX2Vri", "title": "Save Nature", "gif_url": "https://media.giphy.com/media/3oEduSbSGpGaRX2Vri/giphy.gif", "preview_url": "https://media.giphy.com/media/3oEduSbSGpGaRX2Vri/giphy.gif", "width": 480, "height": 270},
    {"gif_id": "xT9IgG50Fb7Mi0prBC", "title": "Energy Saving", "gif_url": "https://media.giphy.com/media/xT9IgG50Fb7Mi0prBC/giphy.gif", "preview_url": "https://media.giphy.com/media/xT9IgG50Fb7Mi0prBC/giphy.gif", "width": 480, "height": 270}
]
DELETE_CODE_TTL_SECONDS = 10 * 60
DELETE_CODE_SESSION_KEY = "account_delete_code"
DELETE_CODE_EXP_SESSION_KEY = "account_delete_code_exp"
DELETE_CODE_VERIFIED_SESSION_KEY = "account_delete_code_verified"

# --- DB MODELLERİ ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    public_id = db.Column(db.String(24), unique=True, nullable=True, index=True)
    email = db.Column(db.String(120), nullable=True)
    password = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(40), nullable=True)
    full_name = db.Column(db.String(120), nullable=True)
    birth_date = db.Column(db.String(10), nullable=True)
    education_level = db.Column(db.String(30), nullable=True) # ilkokul, lise, lisans...
    carbon_score = db.Column(db.Float, default=0.0)
    is_moderator = db.Column(db.Boolean, default=False, nullable=False)
    is_owner = db.Column(db.Boolean, default=False, nullable=False)
    avatar_path = db.Column(db.String(255), nullable=True)
    preview_media_path = db.Column(db.String(255), nullable=True)
    last_username_change = db.Column(db.String(30), nullable=True)


class CarbonRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    score = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(20), nullable=False, default="quiz")
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "entry_date", name="uq_carbon_record_user_date"),
    )


class ForumPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), nullable=False, default="genel")
    attachment_path = db.Column(db.String(255), nullable=True)
    attachment_name = db.Column(db.String(255), nullable=True)
    attachment_kind = db.Column(db.String(20), nullable=True)
    approval_status = db.Column(db.String(20), nullable=False, default=POST_APPROVAL_APPROVED, index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    moderation_note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ForumComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("forum_post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    attachment_path = db.Column(db.String(255), nullable=True)
    attachment_name = db.Column(db.String(255), nullable=True)
    attachment_kind = db.Column(db.String(20), nullable=True)
    reply_to_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class ForumLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("forum_post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("post_id", "user_id", name="uq_forum_like_post_user"),
    )


class SocialFollow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    following_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("follower_id", "following_id", name="uq_social_follow_pair"),
    )


class GifFavorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    gif_id = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    preview_url = db.Column(db.String(500), nullable=False)
    gif_url = db.Column(db.String(500), nullable=False)
    width = db.Column(db.Integer, nullable=False, default=0)
    height = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "gif_id", name="uq_gif_favorite_user_gif"),
    )

# Veritabanını Güncelleme Yardımcısı
def ensure_schema():
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if "user" in table_names:
        cols = [c["name"] for c in inspector.get_columns("user")]
        missing = {
            "education_level": "VARCHAR(30)", "carbon_score": "FLOAT DEFAULT 0.0",
            "nickname": "VARCHAR(40)", "full_name": "VARCHAR(120)",
            "avatar_path": "VARCHAR(255)", "preview_media_path": "VARCHAR(255)",
            "last_username_change": "VARCHAR(30)",
            "public_id": "VARCHAR(24)",
            "is_moderator": "BOOLEAN DEFAULT 0",
            "is_owner": "BOOLEAN DEFAULT 0"
        }
        for col, type_ in missing.items():
            if col not in cols:
                try: db.session.execute(text(f"ALTER TABLE user ADD COLUMN {col} {type_}")); db.session.commit()
                except: pass
        try:
            db.session.execute(text("UPDATE user SET is_moderator = 0 WHERE is_moderator IS NULL"))
            db.session.execute(text("UPDATE user SET is_owner = 0 WHERE is_owner IS NULL"))
            db.session.execute(text("UPDATE user SET education_level = 'lisans' WHERE education_level = 'yuksek_lisans'"))
            db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_public_id ON user(public_id)"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "forum_post" in table_names:
        forum_cols = [c["name"] for c in inspector.get_columns("forum_post")]
        forum_missing = {
            "attachment_path": "VARCHAR(255)",
            "attachment_name": "VARCHAR(255)",
            "attachment_kind": "VARCHAR(20)",
            "approval_status": "VARCHAR(20) DEFAULT 'approved'",
            "approved_by_id": "INTEGER",
            "approved_at": "DATETIME",
            "moderation_note": "VARCHAR(255)"
        }
        for col, type_ in forum_missing.items():
            if col not in forum_cols:
                try: db.session.execute(text(f"ALTER TABLE forum_post ADD COLUMN {col} {type_}")); db.session.commit()
                except: pass
        try:
            db.session.execute(text("UPDATE forum_post SET approval_status = 'approved' WHERE approval_status IS NULL OR approval_status = ''"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "forum_comment" in table_names:
        comment_cols = [c["name"] for c in inspector.get_columns("forum_comment")]
        comment_missing = {
            "reply_to_id": "INTEGER",
            "attachment_path": "VARCHAR(255)",
            "attachment_name": "VARCHAR(255)",
            "attachment_kind": "VARCHAR(20)"
        }
        for col, type_ in comment_missing.items():
            if col not in comment_cols:
                try: db.session.execute(text(f"ALTER TABLE forum_comment ADD COLUMN {col} {type_}")); db.session.commit()
                except: pass

with app.app_context():
    db.create_all()
    ensure_schema()

# --- YARDIMCI FONKSİYONLAR ---
def get_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def generate_public_id():
    return "EA-" + secrets.token_hex(5).upper()


def unique_public_id():
    while True:
        candidate = generate_public_id()
        exists = User.query.filter_by(public_id=candidate).first()
        if not exists:
            return candidate


def is_user_owner(user):
    return bool(user and bool(getattr(user, "is_owner", False)))


def is_user_moderator(user):
    return bool(user and (bool(getattr(user, "is_moderator", False)) or is_user_owner(user)))


def forum_badge_for_user(user):
    if not user:
        return {"name": "Rookie", "type": "score"}
    if is_user_owner(user):
        return {"name": "Owner", "type": "owner"}
    if is_user_moderator(user):
        return {"name": "Moderator", "type": "moderator"}
    return {"name": badge_from_score(user.carbon_score), "type": "score"}


def ensure_user_public_ids():
    users = (
        User.query
        .filter(or_(User.public_id.is_(None), User.public_id == ""))
        .all()
    )
    if not users:
        return
    for user in users:
        user.public_id = unique_public_id()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def ensure_owner_account():
    if not OWNER_USERNAME or not OWNER_PASSWORD:
        return
    owner = User.query.filter_by(username=OWNER_USERNAME).first()
    if not owner:
        owner = User(
            username=OWNER_USERNAME,
            password=generate_password_hash(OWNER_PASSWORD),
            nickname=OWNER_USERNAME,
            public_id=unique_public_id(),
            is_owner=True,
            is_moderator=True
        )
        db.session.add(owner)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    changed = False
    if not owner.public_id:
        owner.public_id = unique_public_id()
        changed = True
    if not owner.is_owner:
        owner.is_owner = True
        changed = True
    if not owner.is_moderator:
        owner.is_moderator = True
        changed = True
    if not check_password_hash(owner.password, OWNER_PASSWORD):
        owner.password = generate_password_hash(OWNER_PASSWORD)
        changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


with app.app_context():
    ensure_user_public_ids()
    ensure_owner_account()


def serialize_record(rec):
    return {
        "id": rec.id,
        "date": rec.entry_date.isoformat(),
        "score": round(float(rec.score), 2),
        "source": rec.source
    }


def badge_from_score(score):
    val = float(score or 0.0)
    if val > 0 and val <= 2:
        return "Diamond"
    if val <= 5:
        return "Gold"
    return "Rookie"


def serialize_forum_user(user):
    if not user:
        return {
            "id": None,
            "public_id": None,
            "username": "silinmis",
            "nickname": "Silinmis Kullanici",
            "display_name": "Silinmis Kullanici",
            "full_name": None,
            "education_level": None,
            "carbon_score": 0.0,
            "badge": {"name": "Rookie", "type": "score"},
            "is_moderator": False,
            "is_owner": False,
            "avatar_url": None,
            "preview_media_url": None
        }
    return {
        "id": user.id,
        "public_id": user.public_id,
        "username": user.username,
        "nickname": user.nickname or user.username,
        "display_name": user.nickname or user.username,
        "full_name": user.full_name,
        "education_level": normalize_education_level(user.education_level, default="yetiskin"),
        "carbon_score": round(float(user.carbon_score or 0), 2),
        "badge": forum_badge_for_user(user),
        "is_moderator": is_user_moderator(user),
        "is_owner": is_user_owner(user),
        "avatar_url": user.avatar_path,
        "preview_media_url": user.preview_media_path
    }


def serialize_forum_comment(
    comment,
    users_by_id,
    comments_by_id=None,
    viewer_user_id=None,
    post_owner_id=None,
    viewer_is_owner=False
):
    author = users_by_id.get(comment.user_id)
    quoted = None
    if comment.reply_to_id:
        parent = (comments_by_id or {}).get(comment.reply_to_id)
        if parent:
            parent_author = users_by_id.get(parent.user_id)
            quoted = {
                "id": parent.id,
                "content": parent.content,
                "author": serialize_forum_user(parent_author),
                "created_at": parent.created_at.isoformat()
            }
    return {
        "id": comment.id,
        "content": comment.content,
        "created_at": comment.created_at.isoformat(),
        "author": serialize_forum_user(author),
        "attachment": (
            {
                "url": comment.attachment_path,
                "name": comment.attachment_name,
                "kind": comment.attachment_kind
            }
            if comment.attachment_path else None
        ),
        "reply_to_id": comment.reply_to_id,
        "reply_to": quoted,
        "can_edit": bool(viewer_user_id and comment.user_id == viewer_user_id),
        "can_delete": bool(
            viewer_user_id and (
                comment.user_id == viewer_user_id
                or post_owner_id == viewer_user_id
                or viewer_is_owner
            )
        )
    }


def get_social_attachment_kind(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ALLOWED_SOCIAL_IMAGE_EXTENSIONS:
        return "image", ext
    if ext in ALLOWED_SOCIAL_GIF_EXTENSIONS:
        return "gif", ext
    if ext in ALLOWED_SOCIAL_FILE_EXTENSIONS:
        return "file", ext
    return None, ext


def save_social_attachment(upload, user_id):
    original_name = secure_filename(upload.filename or "").strip()
    if not original_name:
        raise ValueError("Dosya adi gecersiz.")

    kind, ext = get_social_attachment_kind(original_name)
    if kind is None:
        raise ValueError("Sadece fotograf, GIF ve dosya yukleyebilirsin.")

    stamp = int(time.time() * 1000)
    token = os.urandom(4).hex()
    saved_name = f"social_{user_id}_{stamp}_{token}.{ext}"
    abs_path = os.path.join(SOCIAL_UPLOAD_FOLDER, saved_name)
    upload.save(abs_path)

    return {
        "path": f"/static/uploads/social/{saved_name}",
        "name": original_name[:255],
        "kind": kind
    }


def remove_social_attachment(path):
    rel = (path or "").strip()
    prefix = "/static/uploads/social/"
    if not rel.startswith(prefix):
        return
    fname = rel[len(prefix):].strip()
    if not fname:
        return
    base = os.path.abspath(SOCIAL_UPLOAD_FOLDER)
    abs_path = os.path.abspath(os.path.join(SOCIAL_UPLOAD_FOLDER, fname))
    if not abs_path.startswith(base + os.sep):
        return
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def safe_int(raw, default=0):
    try:
        return max(int(float(raw)), 0)
    except (TypeError, ValueError):
        return default


def is_allowed_giphy_url(url):
    raw = str(url or "").strip()
    if not raw:
        return False
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return False
    host = (parsed.netloc or "").split(":")[0].lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    return host.endswith("giphy.com") or host.endswith("giphyusercontent.com")


def parse_giphy_attachment(data):
    gif_id = str(data.get("giphy_id") or "").strip()
    gif_url = str(data.get("giphy_url") or "").strip()
    preview_url = str(data.get("giphy_preview_url") or "").strip()
    title = str(data.get("giphy_title") or "").strip()

    if not any([gif_id, gif_url, preview_url, title]):
        return None
    if not gif_id or not gif_url:
        raise ValueError("Giphy GIF secimi gecersiz.")
    if len(gif_id) > 80:
        raise ValueError("Giphy GIF kimligi gecersiz.")
    if not is_allowed_giphy_url(gif_url):
        raise ValueError("Sadece Giphy GIF baglantilari destekleniyor.")
    if preview_url and not is_allowed_giphy_url(preview_url):
        raise ValueError("Sadece Giphy onizleme baglantisi kullanilabilir.")

    safe_title = re.sub(r"\s+", " ", title).strip()[:255]
    if not safe_title:
        safe_title = f"Giphy GIF {gif_id}"

    return {
        "gif_id": gif_id,
        "path": gif_url,
        "preview_url": preview_url or gif_url,
        "name": safe_title,
        "kind": "gif"
    }


def normalize_giphy_item(raw):
    if not isinstance(raw, dict):
        return None
    gif_id = str(raw.get("id") or "").strip()
    if not gif_id:
        return None

    images = raw.get("images") or {}
    original = images.get("original") or {}
    fixed_width = images.get("fixed_width") or {}
    fixed_small = images.get("fixed_width_small") or {}

    gif_url = str(
        original.get("url")
        or fixed_width.get("url")
        or fixed_small.get("url")
        or ""
    ).strip()
    preview_url = str(
        fixed_width.get("webp")
        or fixed_width.get("url")
        or fixed_small.get("url")
        or gif_url
    ).strip()

    if not gif_url or not is_allowed_giphy_url(gif_url):
        return None
    if not preview_url or not is_allowed_giphy_url(preview_url):
        preview_url = gif_url

    title = re.sub(r"\s+", " ", str(raw.get("title") or "").strip())[:255]
    if not title:
        title = f"Giphy GIF {gif_id}"

    width = safe_int(original.get("width") or fixed_width.get("width"), default=0)
    height = safe_int(original.get("height") or fixed_width.get("height"), default=0)

    return {
        "gif_id": gif_id,
        "title": title,
        "gif_url": gif_url,
        "preview_url": preview_url,
        "width": width,
        "height": height
    }


def giphy_api_get(endpoint, params=None):
    if not GIPHY_API_KEY:
        raise ValueError("GIPHY_API_KEY ayari yapilmamis.")
    p = dict(params or {})
    p["api_key"] = GIPHY_API_KEY
    url = f"{GIPHY_API_BASE}/{endpoint}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "eco-access/1.0"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    payload = json.loads(raw.decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(data, list):
        return []
    items = []
    for row in data:
        normalized = normalize_giphy_item(row)
        if normalized:
            items.append(normalized)
    return items


def serialize_gif_favorite(fav):
    return {
        "gif_id": fav.gif_id,
        "title": fav.title,
        "gif_url": fav.gif_url,
        "preview_url": fav.preview_url,
        "width": int(fav.width or 0),
        "height": int(fav.height or 0),
        "created_at": fav.created_at.isoformat() if fav.created_at else None
    }


def fallback_giphy_items(query="", limit=18):
    q = str(query or "").strip().lower()
    rows = GIPHY_FALLBACK_ITEMS
    if q:
        rows = [r for r in rows if q in str(r.get("title") or "").lower()]
    if not rows:
        rows = GIPHY_FALLBACK_ITEMS
    return rows[:limit]


def following_ids_for_user(user_id):
    return {
        fid for (fid,) in (
            db.session.query(SocialFollow.following_id)
            .filter(SocialFollow.follower_id == user_id)
            .all()
        )
    }


def can_view_post(user, post):
    if not post:
        return False
    status = (post.approval_status or POST_APPROVAL_APPROVED).strip().lower()
    if status == POST_APPROVAL_APPROVED:
        return True
    if not user:
        return False
    if is_user_moderator(user):
        return True
    return post.user_id == user.id


def parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "on"}:
        return True
    if txt in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_education_level(value, default=None):
    txt = str(value or "").strip().lower()
    if not txt:
        return default
    txt = LEGACY_EDUCATION_MAP.get(txt, txt)
    if txt not in EDUCATION_LEVELS:
        return None
    return txt


def period_stats(user_id, days):
    start = date.today() - timedelta(days=days - 1)
    rows = (
        CarbonRecord.query
        .filter(CarbonRecord.user_id == user_id, CarbonRecord.entry_date >= start)
        .order_by(CarbonRecord.entry_date.desc())
        .all()
    )
    values = [float(r.score) for r in rows]
    count = len(values)
    avg_val = round(sum(values) / count, 2) if count else 0.0
    min_val = round(min(values), 2) if count else 0.0
    max_val = round(max(values), 2) if count else 0.0
    return {
        "count": count,
        "avg": avg_val,
        "min": min_val,
        "max": max_val,
        "entries": [serialize_record(r) for r in rows]
    }


def save_daily_score(user, score, source="quiz", details=None):
    today = date.today()
    existing = CarbonRecord.query.filter_by(user_id=user.id, entry_date=today).first()
    if existing:
        return False, existing

    details_dump = json.dumps(details, ensure_ascii=False) if details is not None else None
    rec = CarbonRecord(
        user_id=user.id,
        entry_date=today,
        score=float(score),
        source=source,
        details_json=details_dump
    )
    db.session.add(rec)
    user.carbon_score = float(score)
    try:
        db.session.commit()
        return True, rec
    except IntegrityError:
        db.session.rollback()
        existing = CarbonRecord.query.filter_by(user_id=user.id, entry_date=today).first()
        return False, existing


def carbon_ai_comment(user):
    weekly = period_stats(user.id, 7)
    monthly = period_stats(user.id, 30)
    yearly = period_stats(user.id, 365)

    if yearly["count"] == 0:
        return (
            "Henuz kaydin yok. Bugun bir kez karbon analizi yap, "
            "yarindan itibaren haftalik-aylik-yillik trendini AI ile yorumlayayim. "
            "Ilk adim olarak ulasimda bir kisa rotayi yuruyus veya toplu tasima ile degistir."
        )

    ai_client = get_ai_client()
    if ai_client is None:
        raise RuntimeError("AI istemcisi hazir degil.")

    prompt = (
        "Sen karbon ayak izi koocusun. Verilen kullanici verisine gore cok kisa bir yorum yaz.\n"
        "Cevap Turkce olsun, en fazla 4 cumle olsun, 1 somut aksiyon maddesi icsin.\n"
        f"Kullanici: {user.nickname or user.username}\n"
        f"7 gun: ortalama {weekly['avg']} kg, kayit {weekly['count']}\n"
        f"30 gun: ortalama {monthly['avg']} kg, kayit {monthly['count']}\n"
        f"365 gun: ortalama {yearly['avg']} kg, kayit {yearly['count']}\n"
        f"Son skor: {float(user.carbon_score or 0):.2f} kg\n"
    )
    resp = ai_client.chat.completions.create(
        model=get_ai_model(),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=220,
        temperature=0.2
    )
    out = (resp.choices[0].message.content or "").strip()
    if not out:
        raise RuntimeError("AI bos cevap dondu.")
    return out


def _normalize_text_line(value, max_len=220):
    txt = re.sub(r"\s+", " ", str(value or "").strip())
    return txt[:max_len]


def _normalize_quiz_details(details):
    rows = details if isinstance(details, list) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        normalized.append({
            "category": _normalize_text_line(row.get("category") or "Genel", 40),
            "question": _normalize_text_line(row.get("question") or "", 220),
            "answer": _normalize_text_line(row.get("answer") or "", 140),
            "score": round(max(score, 0.0), 2)
        })
    return normalized


def fallback_quiz_feedback(level, score, details):
    lvl = normalize_education_level(level, default="yetiskin")
    s = float(score or 0.0)
    if s <= 15:
        intro = "Karbon ayak izin dusuk seviyede. Gayet iyi gidiyorsun."
    elif s <= 30:
        intro = "Karbon ayak izin orta seviyede. Kucuk degisikliklerle hizla dusurulebilir."
    else:
        intro = "Karbon ayak izin yuksek seviyede. En cok etki eden aliskanliklari once hedeflemek faydali."

    top = sorted(details, key=lambda x: x["score"], reverse=True)[:3]
    category_tips = {
        "Ulasim": "Haftada en az 2 gun toplu tasima veya yuruyus dene.",
        "Enerji": "Isitma derecesini 1-2 derece dusurup gereksiz cihazlari prizden cek.",
        "Beslenme": "Haftada 2 ogunde et yerine bitkisel protein sec.",
        "Atik": "Tek kullanim urunleri azalt, yeniden kullanilabilir urunlere gec.",
        "Alisveris": "Ihtiyac listesiyle alisveris yapip plansiz tuketimi azalt.",
        "Dijital": "Yuksek cozumurlukte gereksiz streaming suresini kisalt."
    }

    picked = []
    for row in top:
        cat = row.get("category") or "Genel"
        if cat in category_tips and category_tips[cat] not in picked:
            picked.append(category_tips[cat])
    if not picked:
        picked.append("Bu hafta tek bir aliskanligi sec ve her gun uygulayarak olculebilir azaltim hedefi koy.")

    tone_map = {
        "ilkokul": "Bunu oyun gibi dusun: her gun bir doga dostu secim yap.",
        "ortaokul": "Her gun bir adimla baslayip haftalik seri olusturabilirsin.",
        "lise": "Kucuk ama duzenli kararlar uzun vadede buyuk fark yaratir.",
        "lisans": "Davranis degisimi icin haftalik takip ve olcum yapman etkili olur.",
        "yetiskin": "Rutinde kalici degisiklik icin ulasim ve enerji tarafinda net hedef belirle."
    }
    tone = tone_map.get(lvl, tone_map["yetiskin"])

    return f"{intro} {picked[0]} {tone}"


def quiz_ai_feedback(user, score, details):
    norm_details = _normalize_quiz_details(details)
    level = normalize_education_level(getattr(user, "education_level", None), default="yetiskin")
    if not norm_details:
        return fallback_quiz_feedback(level, score, norm_details)

    top = sorted(norm_details, key=lambda x: x["score"], reverse=True)[:6]
    top_lines = "\n".join([
        f"- [{row['category']}] {row['question']} -> {row['answer']} ({row['score']} puan)"
        for row in top
    ])

    ai_client = get_ai_client()
    if ai_client is None:
        return fallback_quiz_feedback(level, score, norm_details)

    prompt = (
        "Sen ECO-ACCESS karbon koocusun.\n"
        "Kullanici quiz sonucuna gore kisa ve net, eylem odakli geri bildirim yaz.\n"
        "Kurallar:\n"
        "1) Turkce yaz.\n"
        "2) En fazla 5 cumle.\n"
        "3) En az 3 somut adim ver.\n"
        "4) Cevabi kullanicinin egitim seviyesine uygun sade dilde yaz.\n"
        f"Kullanici egitim seviyesi: {level}\n"
        f"Toplam gunluk karbon skoru: {float(score or 0.0):.2f} kg CO2e\n"
        "En yuksek etkiye sahip cevaplar:\n"
        f"{top_lines}\n"
    )
    try:
        resp = ai_client.chat.completions.create(
            model=get_ai_model(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=280,
            temperature=0.2
        )
        out = _normalize_text_line(resp.choices[0].message.content if resp and resp.choices else "", 700)
        if out:
            return out
    except Exception as e:
        print(f"Quiz AI feedback hatasi: {e}")
    return fallback_quiz_feedback(level, score, norm_details)

def is_valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(email or "").strip()))


def smtp_is_configured():
    sender = str(SMTP_EMAIL or "").strip().lower()
    password = str(SMTP_PASSWORD or "").strip()
    if not sender or not password:
        return False
    if sender == "seninmailin@gmail.com":
        return False
    if password == "buraya_app_password_gelecek":
        return False
    return True


def send_email_message(to_email, subject, body_text):
    target = str(to_email or "").strip()
    if not target:
        return False, "E-posta adresi bulunamadi."
    if not is_valid_email(target):
        return False, "E-posta adresi gecersiz."
    if not smtp_is_configured():
        return False, "SMTP ayarlari eksik."

    try:
        msg = EmailMessage()
        msg.set_content(str(body_text or ""))
        msg["Subject"] = str(subject or "ECO-ACCESS Bildirim")
        msg["From"] = SMTP_EMAIL
        msg["To"] = target

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        return True, None
    except Exception as e:
        print(f"Mail hatasi: {e}")
        return False, str(e)


def send_welcome_email(to_email, name):
    person = str(name or "kullanici").strip() or "kullanici"
    body = (
        f"Merhaba {person},\n\n"
        "ECO-ACCESS ailesine hos geldin.\n"
        "Karbon ayak izini azaltmak icin attigin adim degerli.\n\n"
        "Sevgiler,\nEco-Access Ekibi"
    )
    return send_email_message(to_email, "ECO-ACCESS'e Hos Geldin", body)


def send_delete_code_email(to_email, name, code):
    person = str(name or "kullanici").strip() or "kullanici"
    body = (
        f"Merhaba {person},\n\n"
        "Hesap silme islemi icin dogrulama kodunuz:\n"
        f"{code}\n\n"
        f"Bu kod {DELETE_CODE_TTL_SECONDS // 60} dakika icinde gecerlidir.\n"
        "Bu istegi siz yapmadiysaniz bu e-postayi dikkate almayin.\n\n"
        "Eco-Access"
    )
    return send_email_message(to_email, "ECO-ACCESS Hesap Silme Kodu", body)


def send_email_changed_notice(to_email, name):
    person = str(name or "kullanici").strip() or "kullanici"
    body = (
        f"Merhaba {person},\n\n"
        "Hesabinizin e-posta adresi guncellendi.\n"
        "Bu degisikligi siz yapmadiysaniz hesap guvenliginizi kontrol edin.\n\n"
        "Eco-Access"
    )
    return send_email_message(to_email, "ECO-ACCESS E-posta Guncellendi", body)


def clear_delete_session_state():
    session.pop(DELETE_CODE_SESSION_KEY, None)
    session.pop(DELETE_CODE_EXP_SESSION_KEY, None)
    session.pop(DELETE_CODE_VERIFIED_SESSION_KEY, None)


def remove_uploaded_file(path):
    rel = str(path or "").strip()
    if not rel:
        return
    if rel.startswith("/static/uploads/social/"):
        remove_social_attachment(rel)
        return
    prefix = "/static/uploads/"
    if not rel.startswith(prefix):
        return
    fname = rel[len(prefix):].strip()
    if not fname:
        return
    base = os.path.abspath(UPLOAD_FOLDER)
    abs_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, fname))
    if abs_path != base and not abs_path.startswith(base + os.sep):
        return
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def delete_account_everything(user):
    if not user:
        return False, "Kullanici bulunamadi."
    if is_user_owner(user):
        return False, "Owner hesabi silinemez."

    file_paths = set()
    if user.avatar_path:
        file_paths.add(user.avatar_path)
    if user.preview_media_path:
        file_paths.add(user.preview_media_path)

    user_posts = ForumPost.query.filter_by(user_id=user.id).all()
    post_ids = [p.id for p in user_posts]
    for post in user_posts:
        if post.attachment_path:
            file_paths.add(post.attachment_path)

    user_comments = ForumComment.query.filter_by(user_id=user.id).all()
    user_comment_ids = [c.id for c in user_comments]
    for c in user_comments:
        if c.attachment_path:
            file_paths.add(c.attachment_path)

    if post_ids:
        post_comments = ForumComment.query.filter(ForumComment.post_id.in_(post_ids)).all()
        for c in post_comments:
            if c.attachment_path:
                file_paths.add(c.attachment_path)

    try:
        if user_comment_ids:
            (
                ForumComment.query
                .filter(ForumComment.reply_to_id.in_(user_comment_ids))
                .update({"reply_to_id": None}, synchronize_session=False)
            )

        if post_ids:
            ForumLike.query.filter(ForumLike.post_id.in_(post_ids)).delete(synchronize_session=False)
            ForumComment.query.filter(ForumComment.post_id.in_(post_ids)).delete(synchronize_session=False)
            ForumPost.query.filter(ForumPost.id.in_(post_ids)).delete(synchronize_session=False)

        ForumComment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        ForumLike.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        GifFavorite.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        CarbonRecord.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        SocialFollow.query.filter(
            or_(SocialFollow.follower_id == user.id, SocialFollow.following_id == user.id)
        ).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Hesap silme hatasi: {e}")
        return False, "Hesap silinemedi."

    for path in file_paths:
        remove_uploaded_file(path)
    return True, None

# --- SAYFA ROTALARI (NAVIGATION FIX) ---
@app.route("/")
def index(): return send_from_directory(".", "login.html")

@app.route("/dashboard")
@app.route("/dashboard/home")
def dashboard_home():
    if "user_id" not in session: return redirect("/")
    return render_template("home.html", page="home")

@app.route("/dashboard/calc")
def dashboard_calc():
    if "user_id" not in session: return redirect("/")
    return render_template("calc.html", page="calc")

@app.route("/dashboard/edu")
def dashboard_edu():
    if "user_id" not in session: return redirect("/")
    # ARTIK HOME DEĞİL, EDU.HTML DÖNÜYOR (Fix 1)
    return render_template("edu.html", page="edu")

@app.route("/dashboard/social")
@app.route("/dashboard/forum")
def dashboard_social():
    if "user_id" not in session: return redirect("/")
    return render_template("forum.html", page="social")


@app.route("/dashboard/social/search")
def dashboard_social_search():
    if "user_id" not in session:
        return redirect("/")
    return render_template("social_search.html", page="social")


@app.route("/dashboard/social/user/<int:user_id>")
def dashboard_social_user(user_id):
    if "user_id" not in session:
        return redirect("/")
    return render_template("public_profile.html", page="social", target_user_id=user_id)

@app.route("/dashboard/profile")
def dashboard_profile():
    if "user_id" not in session: return redirect("/")
    return render_template("profile.html", page="profile")

@app.route("/dashboard/settings")
def dashboard_settings():
    if "user_id" not in session: return redirect("/")
    return render_template("settings.html", page="settings")


@app.route("/dashboard/moderation")
def dashboard_moderation():
    if "user_id" not in session:
        return redirect("/")
    user = get_user()
    if not is_user_moderator(user):
        return redirect("/dashboard/social")
    return render_template("moderation.html", page="moderation")


@app.route("/dashboard/admin")
def dashboard_admin():
    if "user_id" not in session:
        return redirect("/")
    user = get_user()
    if not is_user_owner(user):
        return redirect("/dashboard/social")
    return render_template("admin.html", page="admin")

# --- AUTH ---
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    u, p = data.get("username"), data.get("password")
    if not u or not p: return jsonify({"message": "Eksik bilgi"}), 400
    if User.query.filter_by(username=u).first(): return jsonify({"message": "Kullanıcı adı dolu"}), 400
    display_name = str(data.get("display_name") or data.get("nickname") or "").strip()
    edu_level = normalize_education_level(data.get("education_level"), default="yetiskin")
    if len(u) < 3:
        return jsonify({"message": "Kullanıcı adı en az 3 karakter olmalı"}), 400
    if not re.fullmatch(r"[a-zA-Z0-9_]+", str(u)):
        return jsonify({"message": "Kullanıcı adı sadece harf, rakam ve alt çizgi içerebilir"}), 400
    if display_name and len(display_name) > 40:
        return jsonify({"message": "Görünen ad en fazla 40 karakter olabilir"}), 400
    if edu_level is None:
        return jsonify({"message": "Gecersiz egitim seviyesi"}), 400
    
    new_user = User(
        username=u, password=generate_password_hash(p),
        public_id=unique_public_id(),
        email=data.get("email"), nickname=(display_name or u),
        full_name=data.get("full_name"),
        birth_date=data.get("birth_date"),
        education_level=edu_level
    )
    db.session.add(new_user); db.session.commit()
    
    # Mail Gönder (Fix 4)
    if data.get("email"): send_welcome_email(data.get("email"), display_name or u)
    
    return jsonify({"message": "Kayit basarili", "public_id": new_user.public_id}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    if not username:
        return jsonify({"message": "Kullanıcı adı gerekli"}), 400
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password, data.get("password")):
        session["user_id"] = user.id
        return jsonify({"message": "Giriş başarılı"}), 200
    return jsonify({"message": "Hatalı bilgi"}), 401

@app.route("/logout", methods=["POST"])
def logout(): session.clear(); return jsonify({"message": "OK"}), 200

@app.route("/auth/me")
def auth_me():
    user = get_user()
    if not user: return jsonify({"logged_in": False}), 401
    return jsonify({
        "logged_in": True,
        "id": user.id,
        "public_id": user.public_id,
        "username": user.username,
        "nickname": user.nickname,
        "display_name": user.nickname or user.username,
        "avatar_url": user.avatar_path,
        "is_moderator": is_user_moderator(user),
        "is_owner": is_user_owner(user),
        "badge": forum_badge_for_user(user)
    }), 200

@app.route("/profile", methods=["GET", "PUT"])
def profile_api():
    user = get_user()
    if not user: return jsonify({"message": "Yetkisiz"}), 401
    effective_edu = normalize_education_level(user.education_level, default="yetiskin")
    if effective_edu != user.education_level:
        user.education_level = effective_edu
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    
    if request.method == "GET":
        return jsonify({
            "id": user.id,
            "public_id": user.public_id,
            "nickname": user.nickname,
            "display_name": user.nickname or user.username,
            "username": user.username,
            "full_name": user.full_name,
            "birth_date": user.birth_date,
            "email": user.email, "education_level": effective_edu,
            "carbon_score": user.carbon_score, "badge": forum_badge_for_user(user),
            "is_moderator": is_user_moderator(user),
            "is_owner": is_user_owner(user),
            "avatar_url": user.avatar_path, "preview_media_url": user.preview_media_path
        })
    
    data = request.get_json(silent=True) or {}

    if "username" in data:
        incoming_username = str(data.get("username") or "").strip()
        if incoming_username != str(user.username or "").strip():
            return jsonify({"message": "Kullanıcı adı değiştirilemez"}), 400

    display_name_payload = None
    if "display_name" in data:
        display_name_payload = str(data.get("display_name") or "").strip()
    elif "nickname" in data:
        display_name_payload = str(data.get("nickname") or "").strip()
    if display_name_payload is not None:
        if not display_name_payload:
            return jsonify({"message": "Gorunen ad bos olamaz"}), 400
        if len(display_name_payload) > 40:
            return jsonify({"message": "Gorunen ad en fazla 40 karakter olabilir"}), 400
        user.nickname = display_name_payload

    if "full_name" in data:
        user.full_name = str(data.get("full_name") or "").strip() or None

    if "education_level" in data:
        raw_edu = str(data.get("education_level") or "").strip()
        if raw_edu:
            parsed_edu = normalize_education_level(raw_edu, default=None)
            if parsed_edu is None:
                return jsonify({"message": "Gecersiz egitim seviyesi"}), 400
            user.education_level = parsed_edu

    if "birth_date" in data:
        birth_date = str(data.get("birth_date") or "").strip()
        if birth_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", birth_date):
            return jsonify({"message": "Dogum tarihi formati gecersiz"}), 400
        user.birth_date = birth_date or None

    db.session.commit()
    return jsonify({
        "message": "Profil guncellendi",
        "profile": {
            "display_name": user.nickname or user.username,
            "username": user.username,
            "full_name": user.full_name,
            "birth_date": user.birth_date,
            "education_level": user.education_level
        }
    }), 200


@app.route("/profile/email", methods=["POST"])
def profile_update_email():
    user = get_user()
    if not user:
        return jsonify({"message": "Yetkisiz"}), 401

    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"message": "E-posta bos olamaz"}), 400
    if len(email) > 120:
        return jsonify({"message": "E-posta en fazla 120 karakter olabilir"}), 400
    if not is_valid_email(email):
        return jsonify({"message": "E-posta formati gecersiz"}), 400

    old_email = str(user.email or "").strip().lower()
    if email == old_email:
        return jsonify({"message": "E-posta zaten ayni"}), 200

    user.email = email
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "E-posta guncellenemedi"}), 409
    except Exception:
        db.session.rollback()
        return jsonify({"message": "E-posta guncellenemedi"}), 500

    name = user.nickname or user.username or "kullanici"
    ok_new, err_new = send_email_changed_notice(email, name)
    if old_email and old_email != email and is_valid_email(old_email):
        send_email_message(
            old_email,
            "ECO-ACCESS E-posta Degisikligi",
            (
                "Hesabinizin e-posta adresi degistirildi.\n"
                f"Yeni e-posta: {email}\n\n"
                "Bu degisikligi siz yapmadiysaniz hesap guvenliginizi kontrol edin."
            )
        )

    if ok_new:
        return jsonify({"message": "E-posta guncellendi ve bildirim maili gonderildi."}), 200
    return jsonify({"message": f"E-posta guncellendi ancak mail gonderilemedi: {err_new}"}), 200


@app.route("/profile/password", methods=["POST"])
def profile_update_password():
    user = get_user()
    if not user:
        return jsonify({"message": "Yetkisiz"}), 401

    data = request.get_json(silent=True) or {}
    current_password = str(data.get("current_password") or "")
    new_password = str(data.get("new_password") or "")
    if not current_password or not new_password:
        return jsonify({"message": "Mevcut ve yeni sifre gerekli"}), 400
    if not check_password_hash(user.password, current_password):
        return jsonify({"message": "Mevcut sifre yanlis"}), 400
    if len(new_password) < 8:
        return jsonify({"message": "Yeni sifre en az 8 karakter olmali"}), 400
    if current_password == new_password:
        return jsonify({"message": "Yeni sifre mevcut sifre ile ayni olamaz"}), 400

    user.password = generate_password_hash(new_password)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Sifre guncellenemedi"}), 500

    if user.email and is_valid_email(user.email):
        send_email_message(
            user.email,
            "ECO-ACCESS Sifre Degisti",
            (
                "Hesabinizin sifresi degistirildi.\n"
                "Bu islemi siz yapmadiysaniz acilen hesabinizi kontrol edin."
            )
        )
    return jsonify({"message": "Sifre guncellendi"}), 200


@app.route("/account-delete/request-code", methods=["POST"])
def account_delete_request_code():
    user = get_user()
    if not user:
        return jsonify({"message": "Yetkisiz"}), 401
    if is_user_owner(user):
        return jsonify({"message": "Owner hesabi silinemez"}), 403
    if not user.email or not is_valid_email(user.email):
        return jsonify({"message": "Hesap silme icin gecerli bir e-posta gerekli"}), 400

    code = f"{secrets.randbelow(1000000):06d}"
    expires_at = int(time.time()) + DELETE_CODE_TTL_SECONDS
    clear_delete_session_state()
    session[DELETE_CODE_SESSION_KEY] = code
    session[DELETE_CODE_EXP_SESSION_KEY] = expires_at
    session[DELETE_CODE_VERIFIED_SESSION_KEY] = False
    session.modified = True

    name = user.nickname or user.username or "kullanici"
    sent, err = send_delete_code_email(user.email, name, code)
    if not sent:
        clear_delete_session_state()
        return jsonify({"message": f"Dogrulama maili gonderilemedi: {err}"}), 502

    return jsonify({
        "message": "Dogrulama kodu e-posta adresine gonderildi.",
        "expires_in": DELETE_CODE_TTL_SECONDS
    }), 200


@app.route("/account-delete/verify-code", methods=["POST"])
def account_delete_verify_code():
    user = get_user()
    if not user:
        return jsonify({"message": "Yetkisiz"}), 401

    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "").strip()
    expected = str(session.get(DELETE_CODE_SESSION_KEY) or "").strip()
    expires_at = int(session.get(DELETE_CODE_EXP_SESSION_KEY) or 0)
    now_ts = int(time.time())

    if not expected:
        return jsonify({"message": "Once kod istemelisin"}), 400
    if not code:
        return jsonify({"message": "Kod gerekli"}), 400
    if now_ts > expires_at:
        clear_delete_session_state()
        return jsonify({"message": "Kodun suresi doldu. Yeni kod iste."}), 400
    if code != expected:
        return jsonify({"message": "Kod hatali"}), 400

    session[DELETE_CODE_VERIFIED_SESSION_KEY] = True
    session.modified = True
    return jsonify({"message": "Kod dogrulandi. Simdi sifreni girerek silmeyi tamamla."}), 200


@app.route("/account-delete/finalize", methods=["POST"])
def account_delete_finalize():
    user = get_user()
    if not user:
        return jsonify({"message": "Yetkisiz"}), 401

    verified = bool(session.get(DELETE_CODE_VERIFIED_SESSION_KEY))
    expected = str(session.get(DELETE_CODE_SESSION_KEY) or "").strip()
    expires_at = int(session.get(DELETE_CODE_EXP_SESSION_KEY) or 0)
    now_ts = int(time.time())
    if not expected or not verified:
        return jsonify({"message": "Once mail kodunu dogrulaman gerekiyor"}), 403
    if now_ts > expires_at:
        clear_delete_session_state()
        return jsonify({"message": "Kodun suresi doldu. Yeni kod iste."}), 403

    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    if not password:
        return jsonify({"message": "Sifre gerekli"}), 400
    if not check_password_hash(user.password, password):
        return jsonify({"message": "Sifre yanlis"}), 400

    ok, err = delete_account_everything(user)
    clear_delete_session_state()
    if not ok:
        if err == "Owner hesabi silinemez.":
            return jsonify({"message": err}), 403
        return jsonify({"message": err or "Hesap silinemedi"}), 500

    session.clear()
    return jsonify({"message": "Hesap kalici olarak silindi"}), 200


@app.route("/api/social/user/<int:user_id>")
def social_user_profile(user_id):
    viewer = get_user()
    if not viewer:
        return jsonify({"message": "Giris yapin"}), 401

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"message": "Kullanici bulunamadi"}), 404

    followers_count = db.session.query(func.count(SocialFollow.id)).filter(SocialFollow.following_id == user.id).scalar() or 0
    following_count = db.session.query(func.count(SocialFollow.id)).filter(SocialFollow.follower_id == user.id).scalar() or 0
    is_self = viewer.id == user.id
    is_following = (
        False if is_self else
        SocialFollow.query.filter_by(follower_id=viewer.id, following_id=user.id).first() is not None
    )

    return jsonify({
        "id": user.id,
        "public_id": user.public_id,
        "nickname": user.nickname or user.username,
        "display_name": user.nickname or user.username,
        "username": user.username,
        "full_name": user.full_name,
        "education_level": normalize_education_level(user.education_level, default="yetiskin"),
        "carbon_score": round(float(user.carbon_score or 0), 2),
        "badge": forum_badge_for_user(user),
        "is_moderator": is_user_moderator(user),
        "is_owner": is_user_owner(user),
        "avatar_url": user.avatar_path,
        "preview_media_url": user.preview_media_path,
        "followers_count": int(followers_count),
        "following_count": int(following_count),
        "is_self": is_self,
        "is_following": is_following
    }), 200


@app.route("/api/social/search")
def social_search():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    q = str(request.args.get("q") or "").strip()
    try:
        user_limit = min(max(int(request.args.get("user_limit", "30")), 1), 80)
    except ValueError:
        user_limit = 30
    try:
        post_limit = min(max(int(request.args.get("post_limit", "30")), 1), 80)
    except ValueError:
        post_limit = 30

    user_query = User.query
    post_query = ForumPost.query.filter(ForumPost.approval_status == POST_APPROVAL_APPROVED)

    if q:
        like = f"%{q}%"
        user_query = user_query.filter(or_(
            User.username.ilike(like),
            User.nickname.ilike(like),
            User.full_name.ilike(like),
            User.public_id.ilike(like)
        ))

        matching_user_ids = (
            db.session.query(User.id)
            .filter(or_(
                User.username.ilike(like),
                User.nickname.ilike(like),
                User.full_name.ilike(like)
            ))
        )
        matching_post_ids_from_comments = (
            db.session.query(ForumComment.post_id)
            .join(User, User.id == ForumComment.user_id)
            .filter(or_(
                ForumComment.content.ilike(like),
                User.username.ilike(like),
                User.nickname.ilike(like),
                User.full_name.ilike(like)
            ))
        )
        post_query = post_query.filter(or_(
            ForumPost.title.ilike(like),
            ForumPost.content.ilike(like),
            ForumPost.user_id.in_(matching_user_ids),
            ForumPost.id.in_(matching_post_ids_from_comments)
        ))

    users = (
        user_query
        .order_by(User.username.asc())
        .limit(user_limit)
        .all()
    )

    posts = (
        post_query
        .order_by(ForumPost.created_at.desc())
        .limit(post_limit)
        .all()
    )

    user_ids = [u.id for u in users]
    followed_ids = following_ids_for_user(user.id)
    posts_count_by_user = dict(
        db.session.query(ForumPost.user_id, func.count(ForumPost.id))
        .filter(
            ForumPost.user_id.in_(user_ids if user_ids else [-1]),
            ForumPost.approval_status == POST_APPROVAL_APPROVED
        )
        .group_by(ForumPost.user_id)
        .all()
    ) if user_ids else {}

    post_author_ids = {p.user_id for p in posts}
    authors_by_id = {
        u.id: u for u in (
            User.query.filter(User.id.in_(post_author_ids)).all() if post_author_ids else []
        )
    }

    users_payload = []
    for row in users:
        users_payload.append({
            "id": row.id,
            "profile": serialize_forum_user(row),
            "posts_count": int(posts_count_by_user.get(row.id, 0)),
            "is_following": row.id in followed_ids,
            "is_self": row.id == user.id
        })

    posts_payload = []
    for row in posts:
        posts_payload.append({
            "id": row.id,
            "title": row.title,
            "content_preview": (row.content or "")[:220],
            "created_at": row.created_at.isoformat(),
            "author": serialize_forum_user(authors_by_id.get(row.user_id))
        })

    return jsonify({
        "query": q,
        "users": users_payload,
        "posts": posts_payload,
        "counts": {
            "users": len(users_payload),
            "posts": len(posts_payload)
        }
    }), 200


@app.route("/save_score", methods=["POST"])
def save_score():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    data = request.get_json(silent=True) or {}
    raw_score = data.get("score")
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return jsonify({"message": "Gecersiz skor"}), 400

    if score < 0:
        return jsonify({"message": "Skor negatif olamaz"}), 400

    details = data.get("details")
    ok, rec = save_daily_score(user, score, source="quiz", details=details)
    if not ok:
        return jsonify({
            "message": "Bugün zaten karbon analizi yaptın. Yarın tekrar deneyebilirsin.",
            "today_score": round(float(rec.score), 2) if rec else None,
            "date": rec.entry_date.isoformat() if rec else date.today().isoformat()
        }), 409
    feedback = quiz_ai_feedback(user, score, details)

    return jsonify({
        "message": "Skor kaydedildi.",
        "record": serialize_record(rec),
        "ai_feedback": feedback
    }), 201


@app.route("/api/carbon/overview")
def carbon_overview():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    today_rec = CarbonRecord.query.filter_by(user_id=user.id, entry_date=date.today()).first()
    latest_records = (
        CarbonRecord.query
        .filter_by(user_id=user.id)
        .order_by(CarbonRecord.entry_date.desc())
        .limit(10)
        .all()
    )
    return jsonify({
        "can_calculate_today": today_rec is None,
        "today_record": serialize_record(today_rec) if today_rec else None,
        "weekly": period_stats(user.id, 7),
        "monthly": period_stats(user.id, 30),
        "yearly": period_stats(user.id, 365),
        "latest": [serialize_record(r) for r in latest_records]
    }), 200


@app.route("/api/carbon/comment")
def carbon_comment():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    try:
        comment = carbon_ai_comment(user)
        return jsonify({"comment": comment}), 200
    except Exception as e:
        print(f"Carbon Comment AI Hatasi: {e}")
        return jsonify({"comment": f"AI yorumu alinamadi: {e}"}), 502


@app.route("/api/giphy/search")
def giphy_search():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    q = str(request.args.get("q") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", "18")), 1), 30)
    except ValueError:
        limit = 18

    params = {
        "limit": limit,
        "rating": "pg-13",
        "lang": "tr"
    }
    endpoint = "search"
    if q:
        params["q"] = q
    else:
        endpoint = "trending"

    fallback = False
    message = ""
    try:
        items = giphy_api_get(endpoint, params)
        if not items:
            fallback = True
            items = fallback_giphy_items(q, limit)
            message = "Giphy sonucu bos geldi. Yerel GIF listesi gosteriliyor."
    except ValueError as e:
        fallback = True
        items = fallback_giphy_items(q, limit)
        message = str(e)
    except urllib.error.HTTPError as e:
        fallback = True
        items = fallback_giphy_items(q, limit)
        message = f"Giphy HTTP hatasi ({e.code}). Yerel GIF listesi gosteriliyor."
    except Exception as e:
        fallback = True
        items = fallback_giphy_items(q, limit)
        message = f"Giphy servisine ulasilamadi: {e}. Yerel GIF listesi gosteriliyor."

    return jsonify({
        "items": items,
        "query": q,
        "count": len(items),
        "fallback": fallback,
        "message": message
    }), 200


@app.route("/api/giphy/favorites")
def giphy_favorites():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    try:
        limit = min(max(int(request.args.get("limit", "30")), 1), 100)
    except ValueError:
        limit = 30
    rows = (
        GifFavorite.query
        .filter_by(user_id=user.id)
        .order_by(GifFavorite.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "items": [serialize_gif_favorite(r) for r in rows],
        "count": len(rows)
    }), 200


@app.route("/api/giphy/favorite", methods=["POST"])
def giphy_save_favorite():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    data = request.get_json(silent=True) or {}
    payload = {
        "giphy_id": data.get("gif_id") or data.get("id") or "",
        "giphy_url": data.get("gif_url") or data.get("url") or "",
        "giphy_preview_url": data.get("preview_url") or data.get("preview") or "",
        "giphy_title": data.get("title") or ""
    }
    try:
        parsed = parse_giphy_attachment(payload)
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    if not parsed:
        return jsonify({"message": "Favoriye eklemek icin GIF sec"}), 400

    width = safe_int(data.get("width"), default=0)
    height = safe_int(data.get("height"), default=0)
    existing = GifFavorite.query.filter_by(user_id=user.id, gif_id=parsed["gif_id"]).first()
    if existing:
        existing.title = parsed["name"]
        existing.preview_url = parsed["preview_url"]
        existing.gif_url = parsed["path"]
        existing.width = width
        existing.height = height
        fav = existing
    else:
        fav = GifFavorite(
            user_id=user.id,
            gif_id=parsed["gif_id"],
            title=parsed["name"],
            preview_url=parsed["preview_url"],
            gif_url=parsed["path"],
            width=width,
            height=height
        )
        db.session.add(fav)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        fav = GifFavorite.query.filter_by(user_id=user.id, gif_id=parsed["gif_id"]).first()
        if not fav:
            return jsonify({"message": "Favori GIF kaydedilemedi"}), 500
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Favori GIF kaydedilemedi"}), 500

    return jsonify({
        "message": "GIF favorilere eklendi",
        "item": serialize_gif_favorite(fav)
    }), 200


@app.route("/api/giphy/favorite/<string:gif_id>", methods=["DELETE"])
def giphy_delete_favorite(gif_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    gid = str(gif_id or "").strip()[:80]
    if not gid:
        return jsonify({"message": "Gecersiz GIF"}), 400
    fav = GifFavorite.query.filter_by(user_id=user.id, gif_id=gid).first()
    if not fav:
        return jsonify({"message": "Favori GIF bulunamadi"}), 404
    try:
        db.session.delete(fav)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Favori GIF kaldirilamadi"}), 500
    return jsonify({"message": "GIF favorilerden kaldirildi", "gif_id": gid}), 200


@app.route("/api/forum/feed")
def forum_feed():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    page_raw = request.args.get("page", "1")
    limit_raw = request.args.get("limit", "20")
    category = (request.args.get("category") or "").strip().lower()
    search_query = (request.args.get("q") or "").strip()
    feed_mode = (request.args.get("feed") or "for_you").strip().lower()
    if feed_mode not in {"for_you", "following"}:
        feed_mode = "for_you"
    try:
        page = max(int(page_raw), 1)
    except ValueError:
        page = 1
    try:
        limit = min(max(int(limit_raw), 1), 50)
    except ValueError:
        limit = 20

    query = ForumPost.query.filter(ForumPost.approval_status == POST_APPROVAL_APPROVED)
    if category and category != "tum":
        if category not in FORUM_CATEGORIES:
            return jsonify({"message": "Gecersiz kategori"}), 400
        query = query.filter(ForumPost.category == category)

    if search_query:
        like = f"%{search_query}%"
        matching_user_ids = (
            db.session.query(User.id)
            .filter(or_(
                User.username.ilike(like),
                User.nickname.ilike(like),
                User.full_name.ilike(like)
            ))
        )
        matching_post_ids_from_comments = (
            db.session.query(ForumComment.post_id)
            .join(User, User.id == ForumComment.user_id)
            .filter(or_(
                ForumComment.content.ilike(like),
                User.username.ilike(like),
                User.nickname.ilike(like),
                User.full_name.ilike(like)
            ))
        )
        query = query.filter(or_(
            ForumPost.title.ilike(like),
            ForumPost.content.ilike(like),
            ForumPost.user_id.in_(matching_user_ids),
            ForumPost.id.in_(matching_post_ids_from_comments)
        ))

    followed_ids = following_ids_for_user(user.id)
    if feed_mode == "following":
        author_scope = set(followed_ids)
        if not author_scope:
            return jsonify({
                "posts": [],
                "page": page,
                "has_more": False,
                "categories": sorted(FORUM_CATEGORIES),
                "feed_mode": feed_mode
            }), 200
        query = query.filter(ForumPost.user_id.in_(author_scope))

    posts = (
        query.order_by(ForumPost.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    if not posts:
        return jsonify({
            "posts": [],
            "page": page,
            "has_more": False,
            "categories": sorted(FORUM_CATEGORIES),
            "feed_mode": feed_mode
        }), 200

    post_ids = [p.id for p in posts]
    post_author_ids = {p.user_id for p in posts}

    like_counts = dict(
        db.session.query(ForumLike.post_id, func.count(ForumLike.id))
        .filter(ForumLike.post_id.in_(post_ids))
        .group_by(ForumLike.post_id)
        .all()
    )
    comment_counts = dict(
        db.session.query(ForumComment.post_id, func.count(ForumComment.id))
        .filter(ForumComment.post_id.in_(post_ids))
        .group_by(ForumComment.post_id)
        .all()
    )
    liked_by_me = {
        pid for (pid,) in (
            db.session.query(ForumLike.post_id)
            .filter(ForumLike.post_id.in_(post_ids), ForumLike.user_id == user.id)
            .all()
        )
    }

    comments = (
        ForumComment.query
        .filter(ForumComment.post_id.in_(post_ids))
        .order_by(ForumComment.created_at.desc())
        .all()
    )
    comments_by_id = {c.id: c for c in comments}
    preview_comments = {}
    comment_author_ids = set()
    for c in comments:
        comment_author_ids.add(c.user_id)
        bucket = preview_comments.setdefault(c.post_id, [])
        if len(bucket) < 3:
            bucket.append(c)

    all_user_ids = list(post_author_ids | comment_author_ids)
    users_by_id = {
        u.id: u for u in (User.query.filter(User.id.in_(all_user_ids)).all() if all_user_ids else [])
    }

    followed_post_authors = {
        uid for (uid,) in (
            db.session.query(SocialFollow.following_id)
            .filter(
                SocialFollow.follower_id == user.id,
                SocialFollow.following_id.in_(post_author_ids if post_author_ids else [-1])
            )
            .all()
        )
    } if post_author_ids else set()

    payload = []
    for post in posts:
        payload.append({
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "category": post.category,
            "approval_status": post.approval_status or POST_APPROVAL_APPROVED,
            "created_at": post.created_at.isoformat(),
            "author": serialize_forum_user(users_by_id.get(post.user_id)),
            "author_is_me": post.user_id == user.id,
            "can_delete": (post.user_id == user.id) or is_user_owner(user),
            "author_followed": post.user_id in followed_post_authors,
            "attachment": (
                {
                    "url": post.attachment_path,
                    "name": post.attachment_name,
                    "kind": post.attachment_kind
                }
                if post.attachment_path else None
            ),
            "stats": {
                "likes": int(like_counts.get(post.id, 0)),
                "comments": int(comment_counts.get(post.id, 0))
            },
            "liked_by_me": post.id in liked_by_me,
            "preview_comments": [
                serialize_forum_comment(
                    c,
                    users_by_id,
                    comments_by_id,
                    viewer_user_id=user.id,
                    post_owner_id=post.user_id,
                    viewer_is_owner=is_user_owner(user)
                )
                for c in preview_comments.get(post.id, [])
            ]
        })

    return jsonify({
        "posts": payload,
        "page": page,
        "has_more": len(posts) == limit,
        "categories": sorted(FORUM_CATEGORIES),
        "feed_mode": feed_mode
    }), 200


@app.route("/api/forum/post", methods=["POST"])
def forum_create_post():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    is_multipart = "multipart/form-data" in (request.content_type or "")
    data = request.form if is_multipart else (request.get_json(silent=True) or {})
    upload = request.files.get("attachment") if is_multipart else None

    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    category = str(data.get("category") or "genel").strip().lower()
    attachment = None
    giphy_attachment = None

    try:
        giphy_attachment = parse_giphy_attachment(data)
    except ValueError as e:
        return jsonify({"message": str(e)}), 400

    if upload and (upload.filename or "").strip():
        try:
            attachment = save_social_attachment(upload, user.id)
        except ValueError as e:
            return jsonify({"message": str(e)}), 400
    elif giphy_attachment:
        attachment = giphy_attachment

    if upload and giphy_attachment:
        return jsonify({"message": "Ayni anda hem dosya hem Giphy GIF gonderemezsin."}), 400

    if not content and not attachment:
        return jsonify({"message": "Yazi veya ek dosya olmadan paylasim yapamazsin."}), 400
    if len(content) > 5000:
        return jsonify({"message": "Icerik en fazla 5000 karakter olabilir"}), 400

    if not title:
        if content:
            title = content[:80]
        elif attachment and attachment["kind"] == "file":
            title = f"Dosya paylasimi: {attachment['name']}"[:160]
        elif attachment and attachment["kind"] == "gif":
            title = "GIF paylasimi"
        else:
            title = "Fotograf paylasimi"
    if len(title) > 160:
        return jsonify({"message": "Baslik en fazla 160 karakter olabilir"}), 400

    if category not in FORUM_CATEGORIES:
        category = "genel"

    auto_approved = is_user_moderator(user)
    approval_status = POST_APPROVAL_APPROVED if auto_approved else POST_APPROVAL_PENDING
    approved_at = datetime.utcnow() if auto_approved else None
    approved_by_id = user.id if auto_approved else None

    post = ForumPost(
        user_id=user.id,
        title=title,
        content=content,
        category=category,
        attachment_path=attachment["path"] if attachment else None,
        attachment_name=attachment["name"] if attachment else None,
        attachment_kind=attachment["kind"] if attachment else None,
        approval_status=approval_status,
        approved_by_id=approved_by_id,
        approved_at=approved_at
    )
    db.session.add(post)
    db.session.commit()

    message = "Gonderi paylasildi" if auto_approved else "Gonderi onay sirasina alindi. Moderator onayindan sonra yayinlanacak."
    return jsonify({
        "message": message,
        "post_id": post.id,
        "status": approval_status
    }), 201


@app.route("/api/forum/post/<int:post_id>", methods=["DELETE"])
def forum_delete_post(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404
    if not can_view_post(user, post):
        return jsonify({"message": "Bu gonderi henuz yayinda degil"}), 403
    if post.user_id != user.id and not is_user_moderator(user):
        return jsonify({"message": "Bu gonderiyi silme yetkin yok"}), 403

    attachment_path = post.attachment_path
    comment_attachments = [
        c.attachment_path
        for c in ForumComment.query.filter_by(post_id=post_id).all()
        if c.attachment_path
    ]
    try:
        ForumComment.query.filter_by(post_id=post_id).delete(synchronize_session=False)
        ForumLike.query.filter_by(post_id=post_id).delete(synchronize_session=False)
        db.session.delete(post)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Gonderi silinemedi"}), 500

    remove_social_attachment(attachment_path)
    for cpath in comment_attachments:
        remove_social_attachment(cpath)
    return jsonify({
        "message": "Gonderi silindi",
        "post_id": post_id
    }), 200


@app.route("/api/forum/mod/pending")
def forum_moderation_pending():
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    if not is_user_moderator(user):
        return jsonify({"message": "Moderator yetkisi gerekli"}), 403

    limit_raw = request.args.get("limit", "50")
    try:
        limit = min(max(int(limit_raw), 1), 200)
    except ValueError:
        limit = 50

    posts = (
        ForumPost.query
        .filter(ForumPost.approval_status == POST_APPROVAL_PENDING)
        .order_by(ForumPost.created_at.asc())
        .limit(limit)
        .all()
    )
    if not posts:
        return jsonify({"posts": [], "count": 0}), 200

    author_ids = {p.user_id for p in posts}
    users_by_id = {
        u.id: u for u in (User.query.filter(User.id.in_(author_ids)).all() if author_ids else [])
    }
    payload = []
    for post in posts:
        payload.append({
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "category": post.category,
            "created_at": post.created_at.isoformat(),
            "author": serialize_forum_user(users_by_id.get(post.user_id)),
            "attachment": (
                {
                    "url": post.attachment_path,
                    "name": post.attachment_name,
                    "kind": post.attachment_kind
                }
                if post.attachment_path else None
            )
        })
    return jsonify({"posts": payload, "count": len(payload)}), 200


@app.route("/api/forum/mod/post/<int:post_id>/approve", methods=["POST"])
def forum_moderation_approve(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    if not is_user_moderator(user):
        return jsonify({"message": "Moderator yetkisi gerekli"}), 403

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404

    post.approval_status = POST_APPROVAL_APPROVED
    post.approved_by_id = user.id
    post.approved_at = datetime.utcnow()
    post.moderation_note = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Onay islemi basarisiz"}), 500

    return jsonify({
        "message": "Gonderi onaylandi",
        "post_id": post.id,
        "status": post.approval_status
    }), 200


@app.route("/api/forum/mod/post/<int:post_id>/reject", methods=["POST"])
def forum_moderation_reject(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401
    if not is_user_moderator(user):
        return jsonify({"message": "Moderator yetkisi gerekli"}), 403

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404

    data = request.get_json(silent=True) or {}
    note = str(data.get("note") or "").strip()[:255]
    post.approval_status = POST_APPROVAL_REJECTED
    post.approved_by_id = user.id
    post.approved_at = datetime.utcnow()
    post.moderation_note = note or None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Red islemi basarisiz"}), 500

    return jsonify({
        "message": "Gonderi reddedildi",
        "post_id": post.id,
        "status": post.approval_status
    }), 200


@app.route("/api/forum/owner/moderator", methods=["POST"])
def forum_owner_set_moderator():
    user = get_user()
    if not user:
        return jsonify({"message": "Giriş yapın"}), 401
    if not is_user_owner(user):
        return jsonify({"message": "Sadece owner moderatör rozeti verebilir"}), 403

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    if not username:
        return jsonify({"message": "Kullanıcı adı gerekli"}), 400
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({"message": "Kullanıcı bulunamadı"}), 404

    desired = parse_bool(data.get("moderator"), default=True)
    if target.id == user.id and not desired:
        return jsonify({"message": "Owner moderatör rozetini kaldıramaz"}), 400
    if target.is_owner:
        desired = True

    target.is_moderator = desired
    if not target.public_id:
        target.public_id = unique_public_id()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Rozet güncellenemedi"}), 500

    return jsonify({
        "message": "Moderatör rozeti güncellendi",
        "user": serialize_forum_user(target)
    }), 200


@app.route("/api/forum/owner/owner-badge", methods=["POST"])
def forum_owner_set_owner_badge():
    user = get_user()
    if not user:
        return jsonify({"message": "Giriş yapın"}), 401
    if not is_user_owner(user):
        return jsonify({"message": "Sadece owner owner rozeti verebilir"}), 403

    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    if not username:
        return jsonify({"message": "Kullanıcı adı gerekli"}), 400
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({"message": "Kullanıcı bulunamadı"}), 404

    desired_owner = parse_bool(data.get("owner"), default=True)
    if target.id == user.id and not desired_owner:
        return jsonify({"message": "Kendi owner rozetini kaldıramazsın"}), 400

    if desired_owner:
        target.is_owner = True
        target.is_moderator = True
    else:
        target.is_owner = False
        target.is_moderator = parse_bool(data.get("keep_moderator"), default=True)

    if not target.public_id:
        target.public_id = unique_public_id()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Owner rozeti güncellenemedi"}), 500

    return jsonify({
        "message": "Owner rozeti güncellendi",
        "user": serialize_forum_user(target)
    }), 200


@app.route("/api/forum/owner/moderators")
def forum_owner_moderator_list():
    user = get_user()
    if not user:
        return jsonify({"message": "Giriş yapın"}), 401
    if not is_user_owner(user):
        return jsonify({"message": "Sadece owner erişebilir"}), 403

    mods = (
        User.query
        .filter(or_(User.is_owner == True, User.is_moderator == True))
        .order_by(User.username.asc())
        .all()
    )
    return jsonify({
        "users": [serialize_forum_user(u) for u in mods]
    }), 200


@app.route("/api/forum/post/<int:post_id>/comments")
def forum_post_comments(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404
    if not can_view_post(user, post):
        return jsonify({"message": "Bu gonderi henuz yayinda degil"}), 403

    limit_raw = request.args.get("limit", "60")
    try:
        limit = min(max(int(limit_raw), 1), 100)
    except ValueError:
        limit = 60

    comments = (
        ForumComment.query
        .filter_by(post_id=post_id)
        .order_by(ForumComment.created_at.asc())
        .limit(limit)
        .all()
    )
    comments_by_id = {c.id: c for c in comments}
    reply_ids = {c.reply_to_id for c in comments if c.reply_to_id}
    missing_reply_ids = [rid for rid in reply_ids if rid not in comments_by_id]
    if missing_reply_ids:
        parent_comments = (
            ForumComment.query
            .filter(ForumComment.id.in_(missing_reply_ids))
            .all()
        )
        for parent in parent_comments:
            if parent.post_id == post_id:
                comments_by_id[parent.id] = parent

    user_ids = list({c.user_id for c in comments} | {c.user_id for c in comments_by_id.values()})
    users_by_id = {
        u.id: u for u in (User.query.filter(User.id.in_(user_ids)).all() if user_ids else [])
    }
    return jsonify({
        "comments": [
            serialize_forum_comment(
                c,
                users_by_id,
                comments_by_id,
                viewer_user_id=user.id,
                post_owner_id=post.user_id,
                viewer_is_owner=is_user_owner(user)
            )
            for c in comments
        ]
    }), 200


@app.route("/api/forum/post/<int:post_id>/comment", methods=["POST"])
def forum_add_comment(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404
    if not can_view_post(user, post):
        return jsonify({"message": "Bu gonderi henuz yayinda degil"}), 403

    is_multipart = "multipart/form-data" in (request.content_type or "")
    data = request.form if is_multipart else (request.get_json(silent=True) or {})
    upload = request.files.get("attachment") if is_multipart else None
    content = str(data.get("content") or "").strip()
    reply_to_raw = data.get("reply_to_id")
    reply_to_id = None
    attachment = None
    giphy_attachment = None

    try:
        giphy_attachment = parse_giphy_attachment(data)
    except ValueError as e:
        return jsonify({"message": str(e)}), 400

    if upload and (upload.filename or "").strip():
        try:
            attachment = save_social_attachment(upload, user.id)
        except ValueError as e:
            return jsonify({"message": str(e)}), 400
    elif giphy_attachment:
        attachment = giphy_attachment

    if upload and giphy_attachment:
        return jsonify({"message": "Ayni anda hem dosya hem Giphy GIF gonderemezsin."}), 400

    if not content and not attachment:
        return jsonify({"message": "Yorum veya ek dosya bos olamaz"}), 400
    if len(content) > 1500:
        return jsonify({"message": "Yorum en fazla 1500 karakter olabilir"}), 400
    if reply_to_raw not in (None, "", 0, "0"):
        try:
            reply_to_id = int(reply_to_raw)
        except (TypeError, ValueError):
            return jsonify({"message": "Gecersiz alinti secimi"}), 400
        if reply_to_id <= 0:
            return jsonify({"message": "Gecersiz alinti secimi"}), 400
        parent_comment = db.session.get(ForumComment, reply_to_id)
        if not parent_comment or parent_comment.post_id != post_id:
            return jsonify({"message": "Alintilanacak yorum bulunamadi"}), 404

    comment = ForumComment(
        post_id=post_id,
        user_id=user.id,
        content=content,
        reply_to_id=reply_to_id,
        attachment_path=attachment["path"] if attachment else None,
        attachment_name=attachment["name"] if attachment else None,
        attachment_kind=attachment["kind"] if attachment else None
    )
    db.session.add(comment)
    db.session.commit()
    comments_by_id = {comment.id: comment}
    users_by_id = {user.id: user}
    if reply_to_id:
        parent = db.session.get(ForumComment, reply_to_id)
        if parent:
            comments_by_id[parent.id] = parent
            parent_user = db.session.get(User, parent.user_id)
            if parent_user:
                users_by_id[parent_user.id] = parent_user
    return jsonify({
        "message": "Yorum eklendi",
        "comment": serialize_forum_comment(
            comment,
            users_by_id,
            comments_by_id,
            viewer_user_id=user.id,
            post_owner_id=post.user_id,
            viewer_is_owner=is_user_owner(user)
        )
    }), 201


@app.route("/api/forum/comment/<int:comment_id>", methods=["DELETE"])
def forum_delete_comment(comment_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    comment = db.session.get(ForumComment, comment_id)
    if not comment:
        return jsonify({"message": "Yorum bulunamadi"}), 404

    post = db.session.get(ForumPost, comment.post_id)
    can_delete = (
        comment.user_id == user.id
        or (post and post.user_id == user.id)
        or is_user_owner(user)
    )
    if not can_delete:
        return jsonify({"message": "Bu yorumu silme yetkin yok"}), 403

    attachment_path = comment.attachment_path
    try:
        (
            ForumComment.query
            .filter(
                ForumComment.post_id == comment.post_id,
                ForumComment.reply_to_id == comment.id
            )
            .update({"reply_to_id": None}, synchronize_session=False)
        )
        db.session.delete(comment)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Yorum silinemedi"}), 500

    remove_social_attachment(attachment_path)

    return jsonify({
        "message": "Yorum silindi",
        "comment_id": comment_id,
        "post_id": comment.post_id
    }), 200


@app.route("/api/forum/comment/<int:comment_id>", methods=["PUT"])
def forum_edit_comment(comment_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    comment = db.session.get(ForumComment, comment_id)
    if not comment:
        return jsonify({"message": "Yorum bulunamadi"}), 404
    if comment.user_id != user.id:
        return jsonify({"message": "Bu yorumu duzenleme yetkin yok"}), 403

    data = request.get_json(silent=True) or {}
    content = str(data.get("content") or "").strip()
    if not content:
        return jsonify({"message": "Yorum bos olamaz"}), 400
    if len(content) > 1500:
        return jsonify({"message": "Yorum en fazla 1500 karakter olabilir"}), 400

    comment.content = content
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Yorum duzenlenemedi"}), 500

    post = db.session.get(ForumPost, comment.post_id)
    comments_by_id = {comment.id: comment}
    users_by_id = {user.id: user}
    if comment.reply_to_id:
        parent = db.session.get(ForumComment, comment.reply_to_id)
        if parent and parent.post_id == comment.post_id:
            comments_by_id[parent.id] = parent
            parent_user = db.session.get(User, parent.user_id)
            if parent_user:
                users_by_id[parent_user.id] = parent_user

    return jsonify({
        "message": "Yorum duzenlendi",
        "comment": serialize_forum_comment(
            comment,
            users_by_id,
            comments_by_id,
            viewer_user_id=user.id,
            post_owner_id=post.user_id if post else None,
            viewer_is_owner=is_user_owner(user)
        )
    }), 200


@app.route("/api/forum/post/<int:post_id>/like", methods=["POST"])
def forum_toggle_like(post_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    post = db.session.get(ForumPost, post_id)
    if not post:
        return jsonify({"message": "Gonderi bulunamadi"}), 404
    if not can_view_post(user, post):
        return jsonify({"message": "Bu gonderi henuz yayinda degil"}), 403

    existing = ForumLike.query.filter_by(post_id=post_id, user_id=user.id).first()
    liked = False
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(ForumLike(post_id=post_id, user_id=user.id))
        liked = True

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        liked = ForumLike.query.filter_by(post_id=post_id, user_id=user.id).first() is not None

    likes_count = db.session.query(func.count(ForumLike.id)).filter(ForumLike.post_id == post_id).scalar() or 0
    return jsonify({
        "liked": liked,
        "likes": int(likes_count)
    }), 200


@app.route("/api/social/follow/<int:target_user_id>", methods=["POST"])
def social_toggle_follow(target_user_id):
    user = get_user()
    if not user:
        return jsonify({"message": "Giris yapin"}), 401

    if user.id == target_user_id:
        return jsonify({"message": "Kendini takip edemezsin."}), 400

    target = db.session.get(User, target_user_id)
    if not target:
        return jsonify({"message": "Kullanici bulunamadi"}), 404

    rel = SocialFollow.query.filter_by(follower_id=user.id, following_id=target_user_id).first()
    following = False
    if rel:
        db.session.delete(rel)
    else:
        db.session.add(SocialFollow(follower_id=user.id, following_id=target_user_id))
        following = True

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        following = SocialFollow.query.filter_by(follower_id=user.id, following_id=target_user_id).first() is not None

    followers_count = db.session.query(func.count(SocialFollow.id)).filter(SocialFollow.following_id == target_user_id).scalar() or 0
    following_count = db.session.query(func.count(SocialFollow.id)).filter(SocialFollow.follower_id == user.id).scalar() or 0
    return jsonify({
        "following": following,
        "target_user_id": target_user_id,
        "followers_count": int(followers_count),
        "my_following_count": int(following_count)
    }), 200

# --- AI CALCULATOR & CHAT (Fix 2 & 3) ---
@app.route("/api/calculate-ai", methods=["POST"])
def calculate_ai():
    user = get_user()
    if not user: return jsonify({"message": "Giriş yapın"}), 401
    
    data = request.get_json() or {}
    user_text = data.get("text", "")
    
    if not user_text: return jsonify({"message": "Boş metin gönderilemez"}), 400

    existing_today = CarbonRecord.query.filter_by(user_id=user.id, entry_date=date.today()).first()
    if existing_today:
        return jsonify({
            "message": "Bugün zaten karbon analizi yaptın. Yarın tekrar deneyebilirsin.",
            "today_score": round(float(existing_today.score), 2),
            "date": existing_today.entry_date.isoformat()
        }), 409
    
    # EĞİTİM SEVİYESİNE GÖRE İSTEM (PROMPT) AYARLAMA
    edu_level = normalize_education_level(user.education_level, default="yetiskin")
    
    prompt = f"""
    Sen bir Karbon Ayak İzi Hesaplama Uzmanısın.
    Kullanıcı Profili: Eğitim Seviyesi: {edu_level}.
    Kullanıcı Girdisi: "{user_text}"
    
    GÖREVİN:
    1. Bu metinden kullanıcının ulaşım, beslenme ve enerji alışkanlıklarını analiz et.
    2. Tahmini bir günlük karbon salınımı (kg CO2e) hesapla.
    3. Kullanıcının eğitim seviyesine ({edu_level}) uygun bir dille kısa bir geri bildirim ve 1 tane somut öneri ver.
    
    ÇIKTI FORMATI (SADECE JSON):
    {{
        "score": 4.5,
        "feedback": "...",
        "recommendation": "..."
    }}
    """

    ai_client = get_ai_client()
    if ai_client is None:
        return jsonify({"message": "AI istemcisi hazir degil. API anahtari ve OpenRouter baglantisini kontrol et."}), 500
    
    try:
        resp = ai_client.chat.completions.create(
            model=get_ai_model(),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"} # JSON zorlaması
        )
        result = json.loads(resp.choices[0].message.content)
        
        # Günlük kaydet (günde bir kez kuralı)
        score_val = float(result.get("score", 0))
        ok, rec = save_daily_score(
            user,
            score_val,
            source="ai",
            details={"text": user_text, "feedback": result.get("feedback"), "recommendation": result.get("recommendation")}
        )
        if not ok:
            return jsonify({
                "message": "Bugün zaten karbon analizi yaptın. Yarın tekrar deneyebilirsin.",
                "today_score": round(float(rec.score), 2) if rec else None,
                "date": rec.entry_date.isoformat() if rec else date.today().isoformat()
            }), 409
        
        return jsonify(result), 200
    except Exception as e:
        print(f"AI Calc Hatası: {e}")
        return jsonify({"message": "Hesaplama yapılamadı, tekrar dene."}), 500

@app.route("/api/ai-chat", methods=["POST"])
def ai_chat():
    user = get_user()
    if not user:
        return jsonify({"response": "Giris yapin"}), 401

    data = request.get_json() or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"response": "Bos mesaj gonderilemez."}), 400

    name = user.nickname or user.username or "kullanici"
    level = normalize_education_level(user.education_level, default="yetiskin")
    score = float(user.carbon_score or 0.0)
    weekly = period_stats(user.id, 7)
    monthly = period_stats(user.id, 30)
    yearly = period_stats(user.id, 365)
    latest_rows = (
        CarbonRecord.query
        .filter_by(user_id=user.id)
        .order_by(CarbonRecord.entry_date.desc())
        .limit(5)
        .all()
    )
    latest_text = ", ".join([f"{r.entry_date.isoformat()}:{float(r.score):.2f}" for r in latest_rows]) or "kayit yok"
    prompt = (
        "Sen Eco-Asistan'sin.\n"
        "Sadece karbon ayak izi, emisyon azaltimi, enerji, ulasim, atik ve beslenme etkisi konularinda cevap ver.\n"
        f"Kullanici: {name}. Egitim seviyesi: {level}. Son karbon skoru: {score:.2f} kg CO2e/gun.\n"
        f"7 gun ortalama: {weekly['avg']} (kayit: {weekly['count']})\n"
        f"30 gun ortalama: {monthly['avg']} (kayit: {monthly['count']})\n"
        f"365 gun ortalama: {yearly['avg']} (kayit: {yearly['count']})\n"
        f"Son kayitlar: {latest_text}\n"
        "Kurallar:\n"
        "1) Her cevabi karbon ayak izi baglamina bagla.\n"
        "2) En fazla 4 cumle yaz.\n"
        "3) En az 1 somut, uygulanabilir adim oner.\n"
        "4) Kullanici alakasiz bir sey sorarsa kibarca karbon ayak izi konusuna geri yonlendir.\n"
        "5) Turkce ve net yaz."
    )

    ai_client = get_ai_client()
    if ai_client is None:
        return jsonify({"response": "AI istemcisi hazir degil. API anahtari ve OpenRouter baglantisini kontrol et."}), 500

    try:
        resp = ai_client.chat.completions.create(
            model=get_ai_model(),
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": msg}
            ],
            max_tokens=300,
            temperature=0.2
        )
        out = (resp.choices[0].message.content or "").strip()
        if not out:
            return jsonify({"response": "AI bos cevap dondu."}), 502
        out_l = out.lower()
        carbon_markers = ["karbon", "emisyon", "co2", "enerji", "ulasim", "atik", "iklim", "tasarruf", "geri donusum"]
        if not any(m in out_l for m in carbon_markers):
            out = "Konuyu karbon ayak izi baglaminda ele alalim. Bugun tek adim: ulasim veya enerji alaninda olculebilir bir azaltim hedefi belirle."
        return jsonify({"response": out}), 200
    except Exception as e:
        print(f"AI Chat Hatasi: {e}")
        err = str(e)
        if "402" in err or "credit" in err.lower():
            return jsonify({"response": "OpenRouter kredi limiti yetersiz. Model kredini veya max token degerini kontrol et."}), 402
        return jsonify({"response": f"AI servisi hatasi: {err}"}), 502

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=debug_mode,
        use_reloader=debug_mode
    )
