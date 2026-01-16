"""Authentication and account management routes."""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services import get_user_service

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Display registration form and handle account creation."""
    if session.get("user_id"):
        return redirect(url_for("main.subject_selection"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        user_service = get_user_service()
        result = user_service.register_user(username, email, password, role)

        if result.get("success"):
            flash("Account created! Please log in.", "success")
            return redirect(url_for("auth.login"))

        error = result.get("error") or "Unable to create account."
        flash(error, "error")

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate a user."""
    if session.get("user_id"):
        return redirect(url_for("main.subject_selection"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user_service = get_user_service()
        user = user_service.authenticate(email, password)

        if user:
            is_admin = user_service.is_admin_user(user)
            session["user_id"] = user.id
            session["username"] = user.username
            session["is_admin"] = is_admin
            session["role"] = "admin" if is_admin else user.role
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for("main.subject_selection"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Log the current user out."""
    if session:
        session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("main.subject_selection"))
