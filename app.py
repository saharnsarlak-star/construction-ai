from flask import Flask
import sqlite3
import os

app = Flask(__name__)

# تابع ساخت دیتابیس
def init_db():
    # دیتابیس در مسیر اصلی پروژه ساخته می‌شود
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # جدول سازمان‌ها (برای ساختار SaaS)
    cursor.execute('''CREATE TABLE IF NOT EXISTS organizations 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)''')
    
    # جدول کاربران
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER, username TEXT, role TEXT)''')
    
    # جدول پروژه‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS projects 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id INTEGER, name TEXT)''')
    
    conn.commit()
    conn.close()

# اجرای تابع ساخت دیتابیس
init_db()

@app.route("/")
def home():
    return "Construction SaaS Database is Ready!"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
