from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Construction Intelligence SaaS is Running"

if __name__ == "__main__":
    app.run()
