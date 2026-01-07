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
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                conversation_id INTEGER,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            )
            """
        )
        ensure_questions_schema(conn)


def ensure_questions_schema(conn):
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("PRAGMA table_info(questions)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "conversation_id" not in columns:
        conn.execute("ALTER TABLE questions ADD COLUMN conversation_id INTEGER")
        conn.commit()


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


def create_conversation(user_id, title="새 대화"):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (user_id, title),
        )
        conn.commit()
        return cursor.lastrowid


def ensure_legacy_conversation(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id
            FROM questions
            WHERE user_id = ? AND conversation_id IS NULL
            LIMIT 1
            """,
            (user_id,),
        )
        if not cursor.fetchone():
            return
        conversation_id = None
        cursor = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE user_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            conversation_id = row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
                (user_id, "이전 대화"),
            )
            conversation_id = cursor.lastrowid
        conn.execute(
            """
            UPDATE questions
            SET conversation_id = ?
            WHERE user_id = ? AND conversation_id IS NULL
            """,
            (conversation_id, user_id),
        )
        conn.commit()


def save_question(user_id, conversation_id, question, answer):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO questions (user_id, conversation_id, question, answer)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, conversation_id, question, answer),
        )
        conn.execute(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP,
                title = CASE WHEN title = '새 대화' THEN ? ELSE title END
            WHERE id = ? AND user_id = ?
            """,
            (question[:20], conversation_id, user_id),
        )
        conn.commit()


def load_conversations(user_id):
    ensure_legacy_conversation(user_id)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def load_questions(user_id, conversation_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT question, answer, created_at
            FROM questions
            WHERE user_id = ? AND conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id, conversation_id),
        )
        return cursor.fetchall()


def get_conversation(user_id, conversation_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT id, title
            FROM conversations
            WHERE id = ? AND user_id = ?
            """,
            (conversation_id, user_id),
        )
        return cursor.fetchone()

init_db()

@app.route('/')
def index():
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


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        if not username or not email:
            return render_template('signup.html', error="아이디와 이메일을 모두 입력해주세요.")
        user_id = get_or_create_user(username, email)
        session["user_id"] = user_id
        session["username"] = username
        return redirect(url_for("index"))
    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route('/history')
def history():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"messages": []})
    conversations = load_conversations(user_id)
    if not conversations:
        return jsonify({"messages": []})
    rows = load_questions(user_id, conversations[0]["id"])
    messages = []
    for row in rows:
        messages.append(
            {
                "role": "user",
                "content": row["question"],
                "isHtml": False,
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": markdown.markdown(
                    row["answer"], extensions=['fenced_code', 'tables']
                ),
                "isHtml": True,
            }
    )
    return jsonify({"messages": messages})

@app.route('/conversations', methods=['GET', 'POST'])
def conversations():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    if request.method == 'POST':
        title = request.json.get("title") if request.is_json else None
        conversation_id = create_conversation(user_id, title or "새 대화")
        return jsonify(
            {
                "conversation": {
                    "id": conversation_id,
                    "title": title or "새 대화",
                }
            }
        )
    rows = load_conversations(user_id)
    return jsonify(
        {
            "conversations": [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "updatedAt": row["updated_at"],
                }
                for row in rows
            ]
        }
    )


@app.route('/conversations/<int:conversation_id>/messages')
def conversation_messages(conversation_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"messages": []}), 401
    if not get_conversation(user_id, conversation_id):
        return jsonify({"messages": []}), 404
    rows = load_questions(user_id, conversation_id)
    messages = []
    for row in rows:
        messages.append(
            {
                "role": "user",
                "content": row["question"],
                "isHtml": False,
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": markdown.markdown(
                    row["answer"], extensions=['fenced_code', 'tables']
                ),
                "isHtml": True,
            }
        )
    return jsonify({"messages": messages})

@app.route('/ask', methods=['POST'])
def ask():
    api_key = os.environ.get("GEMINI_API_KEY")
    user_message = request.json.get('message')
    conversation_id = request.json.get("conversationId")
    if conversation_id is not None:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            conversation_id = None

    if not api_key:
        app.logger.error("GEMINI_API_KEY is not set; cannot call Gemini API.")
        return jsonify({"error": "API 키가 설정되지 않았습니다."}), 500
    
    # 아까 성공한 모델 주소 사용
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
    
    system_instruction = (
        "당신은 LeeGPT의 친절하고 유능한 AI 비서입니다. 사용자의 질문에 대해 "
        "여러 번 다시 묻지 않고, 한 번의 답변에 최대한 상세하고 구체적인 정보를 담아 "
        "전문적으로 답변하세요. 필요한 경우 단계별 설명이나 예시를 포함하세요."
    )

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"parts": [{"text": user_message}]}],
        "tools": [
            {
                "google_search": {}
            }
        ],
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        try:
            response_data = response.json()
        except ValueError:
            response_data = None

        if response.status_code == 200:
            if not response_data:
                raise ValueError("API 응답이 JSON이 아닙니다.")
            raw_text = response_data['candidates'][0]['content']['parts'][0]['text']
            # 마크다운을 HTML로 변환하여 전달 (Bold, 리스트 등 처리)
            html_text = markdown.markdown(raw_text, extensions=['fenced_code', 'tables'])
            if session.get("user_id"):
                user_id = session["user_id"]
                if conversation_id and get_conversation(user_id, conversation_id):
                    active_conversation_id = conversation_id
                else:
                    active_conversation_id = create_conversation(user_id)
                save_question(user_id, active_conversation_id, user_message, raw_text)
            return jsonify({"reply": html_text})
        else:
            app.logger.error(
                "Gemini API error: status=%s response=%s",
                response.status_code,
                response.text,
            )
            if session.get("user_id"):
                user_id = session["user_id"]
                if conversation_id and get_conversation(user_id, conversation_id):
                    active_conversation_id = conversation_id
                else:
                    active_conversation_id = create_conversation(user_id)
                save_question(user_id, active_conversation_id, user_message, "API 에러 발생")
            return jsonify({"error": "API 에러 발생"}), response.status_code
    except Exception as e:
        app.logger.exception("Gemini API request failed: %s", e)
        if session.get("user_id"):
            user_id = session["user_id"]
            if conversation_id and get_conversation(user_id, conversation_id):
                active_conversation_id = conversation_id
            else:
                active_conversation_id = create_conversation(user_id)
            save_question(user_id, active_conversation_id, user_message, str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
