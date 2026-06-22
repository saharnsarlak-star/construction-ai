from flask import Flask
import sqlite3

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS organizations (id INTEGER PRIMARY KEY, name TEXT)')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def hello():
    return "Construction AI is Live!"

if __name__ == "__main__":
    app.run()
