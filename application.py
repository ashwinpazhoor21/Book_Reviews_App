import os
import pdb
import json

from werkzeug.security import check_password_hash, generate_password_hash

from flask import Flask, session, render_template, request, redirect, url_for
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from helpers import get_goodreads

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
# engine = create_engine(os.getenv("DATABASE_URL"))
engine = create_engine(
    "postgres://eahwehioiwzgix:6cbc5e10d3106a72b1d996237366052807c67bd2ad77fbe5d6041a144e607e3a@ec2-54-228-207-163.eu-west-1.compute.amazonaws.com:5432/d1nkcldcl1832o"
)
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    if session.get("logged_in"):
        return render_template("search.html", username=session["user_name"])
    else:
        return render_template("welcome.html")


@app.route("/register", methods=["POST", "GET"])
def register():

    if request.method == "POST":

        # Get form information.
        username = request.form.get("username")
        password = request.form.get("password")

        if (
            db.execute(
                "SELECT * FROM users WHERE username = :username", {"username": username}
            ).rowcount
            > 0
        ):
            return render_template("error.html", message="Username already exists.")
        else:
            # Hash user's password to store in DB
            hashedPassword = generate_password_hash(
                request.form.get("password"), method="pbkdf2:sha256", salt_length=8
            )
            db.execute(
                "INSERT INTO users (username, password) VALUES (:username, :password)",
                {"username": username, "password": hashedPassword},
            )
            db.commit()
            session["user_name"] = username
            session["logged_in"] = True
            return render_template("search.html")
    else:
        return render_template("register.html")


@app.route("/login", methods=["POST"])
def login():
    if request.method == "GET":
        return render_template("welcome.html")
    else:
        # Get form information.
        username = request.form.get("username")
        password = request.form.get("password")

        result = db.execute(
            "SELECT * FROM users WHERE username = :username", {"username": username}
        ).fetchone()

        # pdb.set_trace()

        if result == None or not check_password_hash(result[2], password):
            return render_template(
                "error.html", message="invalid username and/or password"
            )
        else:
            session["user_name"] = username
            session["logged_in"] = True
            return render_template("search.html")


@app.route("/logout")
def logout():
    session["user_name"] = None
    session["logged_in"] = False
    session.clear()
    return render_template("welcome.html")


@app.route("/search", methods=["GET"])
def search():
    if session.get("logged_in"):
        return render_template("search.html")
    else:
        return render_template("error.html", message="Not logged")


@app.route("/search", methods=["POST"])
def books():
    searchqry = request.form.get("search")

    if len(searchqry) == 0:
        searchqry = None

    books = db.execute(
        "SELECT * FROM books WHERE (title LIKE :searchqry) OR (author LIKE :searchqry) OR (isbn LIKE :searchqry)",
        {"searchqry": "%" + searchqry + "%"},
    ).fetchall()

    return render_template("books.html", books=books)


@app.route("/book/<int:book_id>")
def book(book_id):
    book = db.execute("SELECT * FROM books WHERE id = :id", {"id": book_id}).fetchone()

    goodreads = get_goodreads(book.isbn)

    if goodreads.status_code != 200:
        return render_template("error.html", message="404 Error")

    book_all = goodreads.json()
    book_rating = book_all["books"][0]["average_rating"]

    # pdb.set_trace()

    reviews = db.execute(
        "SELECT * FROM reviews LEFT JOIN public.users ON (reviews.user_id = users.id) WHERE book_id = :id",
        {"id": book_id},
    ).fetchall()

    return render_template(
        "book.html", book=book, book_rating=book_rating, reviews=reviews
    )


@app.route("/review/<int:book_id>", methods=["POST"])
def review(book_id):
    stars = request.form.get("stars")
    review = request.form.get("review")
    username = session["user_name"]

    users = db.execute(
        "SELECT username, id from users WHERE username = :username",
        {"username": username},
    ).fetchone()

    if (
        db.execute(
            "SELECT * FROM reviews LEFT JOIN public.users ON (reviews.user_id = users.id) WHERE book_id = :id AND username = :username",
            {"id": book_id, "username": username},
        ).rowcount
        > 0
    ):
        return render_template("error.html", message="Review already exists.")
    else:
        db.execute(
            "INSERT INTO reviews (book_id, user_id, stars, review) VALUES (:book_id, :user_id, :stars, :review)",
            {"book_id": book_id, "user_id": users.id, "stars": stars, "review": review},
        )
        db.commit()

        return redirect(url_for("book", book_id=book_id))


@app.route("/api/<isbn_id>", methods=["GET"])
def api(isbn_id):
    book_api = db.execute(
        "SELECT * FROM books WHERE isbn = :isbn", {"isbn": isbn_id}
    ).fetchone()

    if book_api is None:
        goodreads = get_goodreads(isbn_id)
        if goodreads.status_code != 200:
            return abort(404)
        else:
            book_api = goodreads.json()
            return book_api
    else:
        book_reviews = db.execute(
            "SELECT COUNT(id), AVG(stars) FROM reviews WHERE book_id = :book_id",
            {"book_id": book_api.id},
        ).fetchone()

    resp = {}
    resp["title"] = book_api.title
    resp["author"] = book_api.author
    resp["year"] = book_api.year
    resp["isbn"] = book_api.isbn
    try:
        resp["review_count"] = str(book_reviews[0])
        resp["average_score"] = "% 1.1f" % book_reviews[1]
    except TypeError:
        resp["review_count"] = "Not enough reviews"
        resp["average_score"] = "Not enough reviews"

    json_resp = json.dumps(resp)

    return json_resp, 200
