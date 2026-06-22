from flask import Flask
import sqlite3

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS organizations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER, username TEXT, role TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER, name TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    return "Construction SaaS Database is Ready!"

if __name__ == "__main__":
    app.run()
