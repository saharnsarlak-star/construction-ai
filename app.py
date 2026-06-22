from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def hello():
    return "Construction AI is Live!"

if __name__ == '__main__':
    # این خط کمک می‌کند برنامه روی پورتی که Render می‌دهد اجرا شود
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
