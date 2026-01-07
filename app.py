import os
import sqlite3
import requests
import markdown  # 추가됨
from flask import Flask, render_template, request, jsonify, redirect, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-secret-key")
DB_PATH = os.environ.get("DB_PATH", "jungsupgpt.db")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )


def get_or_create_user(username, email):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id FROM users WHERE username = ? AND email = ?",
            (username, email),
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor = conn.execute(
            "INSERT INTO users (username, email) VALUES (?, ?)",
            (username, email),
        )
        conn.commit()
        return cursor.lastrowid


def save_question(user_id, question, answer):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO questions (user_id, question, answer) VALUES (?, ?, ?)",
            (user_id, question, answer),
        )
        conn.commit()

init_db()

@app.route('/')
def index():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template('index.html', username=session.get("username"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        if not username or not email:
            return render_template('login.html', error="아이디와 이메일을 모두 입력해주세요.")
        user_id = get_or_create_user(username, email)
        session["user_id"] = user_id
        session["username"] = username
        return redirect(url_for("index"))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/ask', methods=['POST'])
def ask():
    if not session.get("user_id"):
        return jsonify({"error": "로그인이 필요합니다."}), 401
    api_key = os.environ.get("GEMINI_API_KEY")
    user_message = request.json.get('message')
    
    # 아까 성공한 모델 주소 사용
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
    
    payload = {"contents": [{"parts": [{"text": user_message}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        if response.status_code == 200:
            raw_text = response_data['candidates'][0]['content']['parts'][0]['text']
            # 마크다운을 HTML로 변환하여 전달 (Bold, 리스트 등 처리)
            html_text = markdown.markdown(raw_text, extensions=['fenced_code', 'tables'])
            save_question(session["user_id"], user_message, raw_text)
            return jsonify({"reply": html_text})
        else:
            save_question(session["user_id"], user_message, "API 에러 발생")
            return jsonify({"error": "API 에러 발생"}), response.status_code
    except Exception as e:
        save_question(session["user_id"], user_message, str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
