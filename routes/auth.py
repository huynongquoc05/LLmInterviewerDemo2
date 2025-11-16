# routes/auth.py
"""
Authentication blueprint - Login/Logout/Register với Google OAuth
"""

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow

from database import (
    create_user, get_user_by_email, get_user_by_google_id,
    verify_password, update_last_login, link_google_account, get_user_by_id
)

auth_bp = Blueprint('auth', __name__)

# ===================================================================
# Google OAuth Configuration
# ===================================================================

# Load credentials từ file
CREDENTIALS_FILE = 'credentials.json'

with open(CREDENTIALS_FILE) as f:
    credentials_data = json.load(f)
    GOOGLE_CLIENT_ID = credentials_data['web']['client_id']
    GOOGLE_CLIENT_SECRET = credentials_data['web']['client_secret']

# Cấu hình Flow (cần disable HTTPS check cho localhost)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Chỉ dùng cho development!


def get_google_flow(redirect_uri=None):
    """Tạo Google OAuth Flow"""
    if redirect_uri is None:
        redirect_uri = url_for('auth.google_callback', _external=True)
    if "fit.neu.edu.vn" in redirect_uri:
        redirect_uri = redirect_uri.replace("http://", "https://")
        print("redirect_uri", redirect_uri)
        if "/iview1" not in redirect_uri:
            redirect_uri = redirect_uri.replace("https://fit.neu.edu.vn", "https://fit.neu.edu.vn/iview1")

    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ],
        redirect_uri=redirect_uri
    )
    return flow


# ===================================================================
# Helper Functions
# ===================================================================

def get_base_path():
    return '/iview1' if 'fit.neu.edu.vn' in request.host else ''


# auth.py

def login_user_session(user):
    """Tạo session cho user sau khi login thành công"""
    session['user'] = {
        'id': user['id'],
        'email': user['email'],
        'name': user['name'],
        'avatar_url': user.get('avatar_url'),
        'login_method': user['login_method'],

        # THÊM DÒNG NÀY
        'role': user.get('role', 'user')  # Lấy role từ DB, nếu lỡ không có thì mặc định là 'user'
    }
    update_last_login(user['id'])


# ===================================================================
# Login/Logout Routes
# ===================================================================

@auth_bp.route("/login", methods=["GET"])
def login_page():
    """Hiển thị trang login"""
    if session.get('user'):
        return redirect(url_for('static.index'))
    return render_template("login.html")


@auth_bp.route("/login", methods=["POST"])
def login_post():
    """Xử lý login bằng email/password"""
    try:
        data = request.get_json() if request.is_json else request.form
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({
                "success": False,
                "error": "Vui lòng nhập đầy đủ email và mật khẩu"
            }), 400

        # Tìm user
        user = get_user_by_email(email)

        if not user:
            return jsonify({
                "success": False,
                "error": "Email chưa được đăng ký"
            }), 401

        # Kiểm tra login method
        if user['login_method'] == 'google' and not user['password_hash']:
            return jsonify({
                "success": False,
                "error": "Tài khoản này chỉ có thể đăng nhập bằng Google"
            }), 401

        # Verify password
        if not verify_password(user, password):
            return jsonify({
                "success": False,
                "error": "Mật khẩu không đúng"
            }), 401

        # Login thành công
        login_user_session(user)

        return jsonify({
            "success": True,
            "message": "Đăng nhập thành công",
            "redirect": get_base_path() + "/"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@auth_bp.route("/logout")
def logout():
    """Đăng xuất"""
    session.clear()
    return redirect(url_for('static.index'))


# ===================================================================
# Register Routes
# ===================================================================

@auth_bp.route("/register", methods=["GET"])
def register_page():
    """Hiển thị trang đăng ký"""
    if session.get('user'):
        return redirect(url_for('static.index'))
    return render_template("register.html")


@auth_bp.route("/register", methods=["POST"])
def register_post():
    """Xử lý đăng ký tài khoản mới"""
    try:
        data = request.get_json() if request.is_json else request.form
        email = data.get('email', '').strip().lower()
        name = data.get('name', '').strip()
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')

        # Validation
        if not email or not name or not password:
            return jsonify({
                "success": False,
                "error": "Vui lòng nhập đầy đủ thông tin"
            }), 400

        if password != confirm_password:
            return jsonify({
                "success": False,
                "error": "Mật khẩu xác nhận không khớp"
            }), 400

        if len(password) < 6:
            return jsonify({
                "success": False,
                "error": "Mật khẩu phải có ít nhất 6 ký tự"
            }), 400

        # Tạo user mới
        user = create_user(email=email, name=name, password=password)

        # Auto login sau khi đăng ký
        login_user_session(user)

        return jsonify({
            "success": True,
            "message": "Đăng ký thành công",
            "redirect": get_base_path() + "/"
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Lỗi hệ thống: " + str(e)
        }), 500


# ===================================================================
# Google OAuth Routes
# ===================================================================

@auth_bp.route("/login/google")
def google_login():
    """Redirect đến Google OAuth"""
    flow = get_google_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    # Lưu state để verify callback
    session['oauth_state'] = state

    return redirect(authorization_url)


@auth_bp.route("/login/callback")
def google_callback():
    """Google OAuth callback handler"""
    try:
        # Verify state
        if request.args.get('state') != session.get('oauth_state'):
            return "Invalid state parameter", 400

        # Exchange authorization code cho tokens
        flow = get_google_flow()
        flow.fetch_token(authorization_response=request.url)

        # Lấy credentials
        credentials = flow.credentials

        # Verify ID token và lấy user info
        idinfo = id_token.verify_oauth2_token(
            credentials.id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )

        # Extract user info
        google_id = idinfo['sub']
        email = idinfo['email'].lower()
        name = idinfo.get('name', email.split('@')[0])
        avatar_url = idinfo.get('picture')

        # Tìm user theo Google ID
        user = get_user_by_google_id(google_id)

        if user:
            # User đã tồn tại với Google ID này
            login_user_session(user)
        else:
            # Kiểm tra email đã tồn tại chưa
            user = get_user_by_email(email)

            if user:
                # Email đã tồn tại (đăng ký bằng password trước đó)
                # → Liên kết tài khoản Google
                link_google_account(user['id'], google_id, avatar_url)
                user = get_user_by_id(user['id'])  # Reload user
                login_user_session(user)
            else:
                # Tạo user mới với Google
                user = create_user(
                    email=email,
                    name=name,
                    google_id=google_id,
                    avatar_url=avatar_url
                )
                login_user_session(user)

        return redirect(url_for('static.index'))

    except Exception as e:
        print(f"❌ Google OAuth error: {e}")
        return f"Authentication failed: {str(e)}", 500


# ===================================================================
# API Endpoints (cho AJAX calls)
# ===================================================================

@auth_bp.route("/api/check-auth")
def check_auth():
    """Kiểm tra trạng thái đăng nhập"""
    if session.get('user'):
        return jsonify({
            "authenticated": True,
            "user": session['user']
        })
    return jsonify({"authenticated": False})