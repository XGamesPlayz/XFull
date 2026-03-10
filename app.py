from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import hashlib
from datetime import datetime, timedelta
import os
import random

# ----------------- Flask Setup -----------------
app = Flask(__name__)
app.secret_key = "xfull_secret_key"

# ----------------- Folders -----------------
POSTERS_FOLDER = "static/posters"
VIDEOS_FOLDER = "static/videos"
TRAILERS_FOLDER = "static/trailers"

os.makedirs(POSTERS_FOLDER, exist_ok=True)
os.makedirs(VIDEOS_FOLDER, exist_ok=True)
os.makedirs(TRAILERS_FOLDER, exist_ok=True)

# ----------------- Database -----------------
DB_FILE = "users.db"

def get_db():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    return db

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_tables():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS shows_movies(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            type TEXT,
            category_id INTEGER,
            poster_file TEXT,
            video_file TEXT,
            trailer_file TEXT,
            upload_date TEXT,
            views INTEGER DEFAULT 0,
            description TEXT,
            uploader TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS episodes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            show_id INTEGER,
            season INTEGER,
            episode INTEGER,
            title TEXT,
            video_file TEXT,
            FOREIGN KEY(show_id) REFERENCES shows_movies(id)
        )
    """)
    default_categories = ["Scary", "Goofy", "Serious", "New", "Hits"]
    for cat in default_categories:
        try:
            db.execute("INSERT INTO categories(name) VALUES(?)", (cat,))
        except sqlite3.IntegrityError:
            pass
    db.commit()
    db.close()

create_tables()

# ----------------- Routes -----------------

# Index (Login/Register)
@app.route("/", methods=["GET","POST"])
def index():
    error_login = None
    error_register = None
    if "user" in session:
        return redirect("/home")

    if request.method == "POST":
        if "register" in request.form:
            username = request.form["register_username"]
            password = hash_password(request.form["register_password"])
            db = get_db()
            try:
                db.execute("INSERT INTO users(username,password) VALUES(?,?)", (username,password))
                db.commit()
                session["user"] = username
                db.close()
                return redirect("/home")
            except sqlite3.IntegrityError:
                error_register = "Username already exists"
                db.close()
        if "login" in request.form:
            username = request.form["login_username"]
            password = hash_password(request.form["login_password"])
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE username=? AND password=?", (username,password)).fetchone()
            db.close()
            if user:
                session["user"] = username
                return redirect("/home")
            else:
                error_login = "Invalid username or password"

    return render_template("index.html", error_login=error_login, error_register=error_register)

# Home page
@app.route("/home")
def home():
    if "user" not in session:
        return redirect("/")
    return render_template("home.html", username=session["user"])

# Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

# Watch page (search filters removed)
@app.route("/watch")
def watch():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    search_query = request.args.get("search","").strip()

    # Load categories (for display, but search ignores type/category)
    categories = db.execute("SELECT * FROM categories").fetchall()
    category_data = []

    # Homepage videos by category
    if not search_query:
        for cat in categories:
            cat_id, cat_name = cat["id"], cat["name"]
            if cat_name=="Hits":
                videos = db.execute("SELECT * FROM shows_movies ORDER BY views DESC LIMIT 10").fetchall()
            elif cat_name=="New":
                two_weeks_ago = datetime.now() - timedelta(days=14)
                videos = db.execute("SELECT * FROM shows_movies WHERE upload_date >= ?", (two_weeks_ago.strftime("%Y-%m-%d"),)).fetchall()
            else:
                videos = db.execute("SELECT * FROM shows_movies WHERE category_id=?", (cat_id,)).fetchall()
            category_data.append({"id":cat_id,"name":cat_name,"videos":videos})
        category_data.sort(key=lambda x: 0 if x["name"]=="Hits" else 1)

    # Search by title only
    search_results = []
    if search_query:
        all_videos = db.execute("SELECT * FROM shows_movies").fetchall()
        for v in all_videos:
            if search_query.lower() in v["title"].lower():
                search_results.append(v)

    # Random movies for homepage display
    random_movies = []
    if not search_query:
        all_movies = db.execute("SELECT * FROM shows_movies").fetchall()
        random_movies = random.sample(all_movies, min(8,len(all_movies))) if all_movies else []

    db.close()
    return render_template("watch.html",
                           categories=category_data,
                           random_movies=random_movies,
                           search_results=search_results,
                           search_query=search_query)

# Video page
@app.route("/video/<int:video_id>")
def video_page(video_id):
    if "user" not in session:
        return redirect("/")
    db = get_db()
    video = db.execute("SELECT * FROM shows_movies WHERE id=?", (video_id,)).fetchone()
    if not video:
        db.close()
        return "Video not found"
    episodes = []
    if video["type"]=="show":
        episodes = db.execute("SELECT * FROM episodes WHERE show_id=? ORDER BY season, episode", (video_id,)).fetchall()
    db.close()
    return render_template("video.html", video=video, episodes=episodes)

# Upload page
@app.route("/upload", methods=["GET","POST"])
def upload():
    if "user" not in session:
        return redirect("/")

    db = get_db()
    categories = db.execute("SELECT * FROM categories WHERE name NOT IN ('Hits','New')").fetchall()
    uploaded_items = db.execute("""
        SELECT sm.id, sm.title, sm.type, c.name, sm.poster_file, sm.uploader, sm.description, sm.category_id
        FROM shows_movies sm
        JOIN categories c ON sm.category_id=c.id
    """).fetchall()

    if request.method=="POST":
        action = request.form.get("action")
        if action=="upload":
            title = request.form["upload_title"]
            type_sm = request.form["upload_type"]
            category_id = int(request.form["upload_category"])
            description = request.form.get("upload_description","")

            poster = request.files.get("upload_poster")
            poster_filename = None
            if poster and poster.filename:
                safe_name = poster.filename.replace(" ","_").replace("/","_")
                poster_filename = f"{datetime.now().timestamp()}_{safe_name}"
                poster.save(os.path.join(POSTERS_FOLDER, poster_filename))

            video_file = request.files.get("upload_video")
            video_filename = None
            if video_file and video_file.filename:
                safe_name = video_file.filename.replace(" ","_").replace("/","_")
                video_filename = f"{datetime.now().timestamp()}_{safe_name}"
                video_file.save(os.path.join(VIDEOS_FOLDER, video_filename))

            trailer_file = request.files.get("upload_trailer")
            trailer_filename = None
            if trailer_file and trailer_file.filename:
                safe_name = trailer_file.filename.replace(" ","_").replace("/","_")
                trailer_filename = f"{datetime.now().timestamp()}_{safe_name}"
                trailer_file.save(os.path.join(TRAILERS_FOLDER, trailer_filename))

            db.execute("""
                INSERT INTO shows_movies(title,type,category_id,poster_file,video_file,trailer_file,upload_date,description,uploader)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                title, type_sm, category_id, poster_filename, video_filename, trailer_filename,
                datetime.now().strftime("%Y-%m-%d"), description, session["user"]
            ))
            db.commit()
            return redirect("/upload")

        elif action=="edit":
            movie_id = int(request.form["movie_id"])
            new_title = request.form["edit_title"]
            new_category = int(request.form["edit_category"])

            video_file = request.files.get("edit_video")
            trailer_file = request.files.get("edit_trailer")

            old_data = db.execute("SELECT * FROM shows_movies WHERE id=?", (movie_id,)).fetchone()
            video_filename = old_data["video_file"]
            trailer_filename = old_data["trailer_file"]

            if video_file and video_file.filename:
                safe_name = video_file.filename.replace(" ","_").replace("/","_")
                video_filename = f"{datetime.now().timestamp()}_{safe_name}"
                video_file.save(os.path.join(VIDEOS_FOLDER, video_filename))

            if trailer_file and trailer_file.filename:
                safe_name = trailer_file.filename.replace(" ","_").replace("/","_")
                trailer_filename = f"{datetime.now().timestamp()}_{safe_name}"
                trailer_file.save(os.path.join(TRAILERS_FOLDER, trailer_filename))

            db.execute("""
                UPDATE shows_movies
                SET title=?, category_id=?, video_file=?, trailer_file=?
                WHERE id=?
            """,(new_title,new_category,video_filename,trailer_filename,movie_id))
            db.commit()
            return redirect("/upload")

        elif action=="delete":
            movie_id = int(request.form["movie_id"])
            db.execute("DELETE FROM shows_movies WHERE id=?", (movie_id,))
            db.commit()
            return redirect("/upload")

    db.close()
    return render_template("upload.html", categories=categories, uploaded_items=uploaded_items)

# ----------------- Run -----------------
if __name__=="__main__":
    print("Starting XFull server on http://127.0.0.1:5000/")
    app.run(host="0.0.0.0", port=5000, debug=True)