import os
import requests
import markdown  # 추가됨
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
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
            return jsonify({"reply": html_text})
        else:
            return jsonify({"error": "API 에러 발생"}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
