"""Authentication routes: register / login / logout.

WHY Flask-Login + @login_required: the Analysis/Irrigation/Cost tables are
per-user records; without login guards one student could open another's
history by guessing URLs. @login_required bounces anonymous users to /login.
WHY werkzeug hashing: see User.set_password — never store plain passwords.

FLASH MESSAGE CONVENTION: the UI is English-only, so flash plain English
strings directly — base.html renders them as-is.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user, current_user

from app.models import db, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # Already logged in? Skip the form — a small UX detail viva panels like.
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        # Field names come from app/templates/auth/register.html (frontend).
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        # Minimal validation: empty fields, password mismatch, duplicates.
        if not username or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return render_template("auth/register.html")
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/register.html")
        # WHY checked separately: the flash key tells the user exactly which
        # one is taken (email vs username) so they know what to change.
        if User.query.filter_by(username=username).first():
            flash("This username is already taken.", "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(email=email).first():
            flash("This email is already registered.", "danger")
            return render_template("auth/register.html")

        user = User(username=username, email=email)
        user.set_password(password)  # hashes — never stores the raw password
        db.session.add(user)
        db.session.commit()
        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        # Field names come from app/templates/auth/login.html (frontend).
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            # WHY one generic message: telling "email wrong" vs "password
            # wrong" leaks which accounts exist to an attacker.
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html")

        # WHY remember=True: keeps the session alive across browser restarts —
        # useful for a farm phone that reopens the app days later.
        login_user(user, remember=True)
        flash("Logged in successfully. Welcome back!", "success")
        # "next" preserves the page the login guard bounced them from.
        next_page = request.args.get("next")
        return redirect(next_page or url_for("main.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))
