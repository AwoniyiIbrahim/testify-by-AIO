from flask import Flask, render_template, redirect, request, url_for, flash, session
from flask_login import UserMixin, login_user, logout_user, LoginManager, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey, func
import time
import requests
import random
import html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path="mail.env")

# App setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("API_KEY")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE")




class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)

# User model
class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(1000))
    results = relationship("TestResult", back_populates="user")

# Test results model
class TestResult(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    score: Mapped[int] = mapped_column(Integer)
    user = relationship("User", back_populates="results")

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)

# Trivia API
Url = os.getenv("URL")
Time = time.strftime('%Y')

@app.route('/')
def home():
    # Leaderboard: best score per user
    leaderboard = db.session.execute(
        db.select(User.name, func.max(TestResult.score).label("best_score"))
        .join(TestResult)
        .group_by(User.id)
        .order_by(func.max(TestResult.score).desc())
    ).all()

    return render_template('index.html',
                           leaderboard=leaderboard,
                           logged_in=current_user.is_authenticated)

@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == "POST":
        hash_and_salted_password = generate_password_hash(
            request.form.get('password'),
            method='pbkdf2:sha256',
            salt_length=8
        )
        new_user = User(
            email=request.form.get('email'),
            password=hash_and_salted_password,
            name=request.form.get('name')
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('register.html', logged_in=current_user.is_authenticated)

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get('email')
        password = request.form.get('password')
        result = db.session.execute(db.select(User).where(User.email == email))
        user = result.scalar()
        if not user:
            flash("That email does not exist, please try again.")
            return redirect(url_for('login'))
        elif not check_password_hash(user.password, password):
            flash('Password incorrect, please try again.')
            return redirect(url_for('login'))
        else:
            login_user(user)
            return redirect(url_for('dashboard'))
    return render_template("login.html", logged_in=current_user.is_authenticated)

@app.route('/test')
@login_required
def test():
    response = requests.get(Url)
    data = response.json()
    questions = []

    for i, item in enumerate(data["results"], 1):
        options = item["incorrect_answers"] + [item["correct_answer"]]
        random.shuffle(options)

        questions.append({
            "id": i,
            "question": html.unescape(item["question"]),
            "options": [html.unescape(opt) for opt in options],
            "answer": html.unescape(item["correct_answer"])
        })

    session["questions"] = questions
    return render_template('test.html', questions=questions)

@app.route('/submit_test', methods=["POST"])
@login_required
def submit_test():
    questions = session.get("questions", [])
    score = 0

    for q in questions:
        selected = request.form.get(f"q{q['id']}")
        if selected == q["answer"]:
            score += 1

    # Save result for the current user
    new_result = TestResult(user_id=current_user.id, score=score)
    db.session.add(new_result)
    db.session.commit()

    return redirect(url_for("show_score", score=score, total=len(questions)))

@app.route('/show_score')
@login_required
def show_score():
    score = request.args.get("score", type=int, default=0)
    total = request.args.get("total", type=int, default=20)
    return render_template("score.html", score=score, total=total)

@app.route('/dashboard')
@login_required
def dashboard():
    highest = db.session.query(func.max(TestResult.score)).filter_by(user_id=current_user.id).scalar() or 0
    return render_template('dashboard.html',
                           name=current_user.name,
                           logged_in=True,
                           highest_score=highest)
@app.route('/send_email',methods=["POST"])
def send_email():
    try:
        email=request.form["email"]
        name=request.form["name"]
        message_content=request.form["message"]

        SENDER_EMAIL=os.getenv("EMAIL_USER")
        SENDER_PASSWORD=os.getenv("EMAIL_PASS")
        RECEIVER_EMAIL=os.getenv("EMAIL_RECEIVE")
        
        message=MIMEMultipart()
        message["From"]=SENDER_EMAIL
        message["To"]=RECEIVER_EMAIL
        message["Subject"]=f"New Contact form submission from {name}"

        body=f"""
        You have a new message from your website contact form:

        Name: {name}
        Email: {email}
        Message: {message_content}
        """
        message.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, message.as_string())
        server.quit()

        flash("✅ Message sent successfully!", "success")

        confirm = MIMEMultipart()
        confirm["From"] = SENDER_EMAIL
        confirm["To"] = email
        confirm["Subject"] = "Thanks for contacting us!"

        confirm_body = f"""
        Hi {name},

        Thanks for reaching out! We’ve received your message and will reply soon.

        Your message:
        {message_content}

        - The Team
        """
        confirm.attach(MIMEText(confirm_body, "plain"))

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, email, confirm.as_string())
        server.quit()

        flash("✅ Confirmation sent to user as well!", "info")
    except Exception as e:
        flash(f"❌ Error sending message: {e}", "danger")
    return redirect("/")


@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/logout')
def logout_route():
    logout_user()
    return redirect(url_for('home'))

@app.context_processor
def inject_time():
    return {'year': Time}

if __name__ == '__main__':
    app.run(debug=True)
