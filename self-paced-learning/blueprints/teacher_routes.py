"""Teacher-specific routes for managing classrooms and student progress."""

from typing import Union

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from services import get_progress_service, get_user_service

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _require_teacher() -> Union[int, Response]:
    """Ensure the current session belongs to a logged-in teacher."""
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id:
        flash("Please log in to access teacher tools.", "warning")
        return redirect(url_for("auth.login"))

    if role != "teacher":
        flash("Teacher access required.", "error")
        return redirect(url_for("main.subject_selection"))

    return int(user_id)


@teacher_bp.route("/students")
def students():
    """Show all students registered in the teacher's classes."""
    teacher_id_or_response = _require_teacher()
    if not isinstance(teacher_id_or_response, int):
        return teacher_id_or_response

    teacher_id = teacher_id_or_response
    user_service = get_user_service()
    teacher = user_service.get_user(teacher_id)
    students = user_service.get_teacher_students(teacher_id)

    return render_template(
        "teacher_students.html",
        students=students,
        code=teacher.code if teacher else None,
    )


@teacher_bp.route("/adjust_tokens", methods=["POST"])
def adjust_tokens():
    """Adjust tokens for a student in the teacher's classes."""
    teacher_id_or_response = _require_teacher()
    if not isinstance(teacher_id_or_response, int):
        return teacher_id_or_response

    teacher_id = teacher_id_or_response
    user_service = get_user_service()

    try:
        student_id = int(request.form.get("student_id", "0"))
        amount = int(request.form.get("amount", "0"))
    except ValueError:
        flash("Invalid token adjustment values.", "error")
        return redirect(url_for("teacher.students"))

    if amount <= 0:
        flash("Token adjustment amount must be greater than 0.", "error")
        return redirect(url_for("teacher.students"))

    action = (request.form.get("action") or "add").strip().lower()
    delta = amount if action == "add" else -amount

    result = user_service.adjust_student_tokens(teacher_id, student_id, delta)
    if result.get("success"):
        flash("Student token balance updated.", "success")
    else:
        flash(result.get("error") or "Unable to update tokens.", "error")

    return redirect(url_for("teacher.students"))


@teacher_bp.route("/remove_student/<int:student_id>", methods=["POST"])
def remove_student(student_id: int):
    """Remove a student from all of the teacher's classes."""
    teacher_id_or_response = _require_teacher()
    if not isinstance(teacher_id_or_response, int):
        return teacher_id_or_response

    teacher_id = teacher_id_or_response
    user_service = get_user_service()
    user_service.remove_student_from_teacher(teacher_id, student_id)
    flash("Student removed from your classes.", "info")
    return redirect(url_for("teacher.students"))


@teacher_bp.route("/student_progress/<int:student_id>")
def student_progress(student_id: int):
    """Display detailed progress for a specific student."""
    teacher_id_or_response = _require_teacher()
    if not isinstance(teacher_id_or_response, int):
        return teacher_id_or_response

    user_service = get_user_service()
    progress_service = get_progress_service()

    student = user_service.get_user(student_id)
    if not student or student.role != "student":
        flash("Student not found.", "error")
        return redirect(url_for("teacher.students"))

    # Verify the student belongs to the teacher to prevent data leaks.
    teacher_students = {
        registered_student.id
        for registered_student in user_service.get_teacher_students(
            teacher_id_or_response
        )
    }
    if student_id not in teacher_students:
        flash("Student is not registered in your classes.", "error")
        return redirect(url_for("teacher.students"))

    progress_summary = progress_service.get_student_progress_summary(student_id)

    return render_template(
        "teacher_student_progress.html",
        student=student,
        progress_summary=progress_summary,
    )
