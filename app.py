from flask import Flask
import sqlite3

app = Flask(__name__)

# تابع ساخت دیتابیس
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # جدول سازمان‌ها (شرکت‌ها)
    cursor.execute('''CREATE TABLE IF NOT EXISTS organizations 
                      (id INTEGER PRIMARY KEY, name TEXT)''')
    # جدول کاربران
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY, org_id INTEGER, username TEXT, role TEXT)''')
    # جدول پروژه‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                      (id INTEGER PRIMARY KEY, org_id INTEGER, name TEXT)''')
    conn.commit()
    conn.close()

# اجرای تابع ساخت در شروع برنامه
init_db()

@app.route("/")
def home():
    return "Construction SaaS Database is Ready!"

if __name__ == "__main__":
    app.run()
