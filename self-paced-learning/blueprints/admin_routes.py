"""Admin Routes Blueprint

Handles all administrative routes including dashboard, subject management,
lesson administration, and system oversight.
"""

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    Response,
    session,
)
from services import get_admin_service, get_data_service, get_user_service
from extensions import db
from typing import Any, Dict, List
from sqlalchemy import func
import os
import json
from datetime import datetime
from models import User, AnonUser, Attempt, Cycle

# Create the Blueprint
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ============================================================================
# ACCESS CONTROL
# ============================================================================


@admin_bp.before_request
def require_admin():
    """Restrict admin routes to authenticated admin users."""
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    if not session.get("is_admin"):
        return redirect(url_for("main.subject_selection"))


# ============================================================================
# DASHBOARD AND OVERVIEW ROUTES
# ============================================================================


@admin_bp.route("/")
@admin_bp.route("")
def admin_dashboard():
    """Admin dashboard overview."""
    try:
        data_service = get_data_service()

        # Use auto-discovery instead of subjects.json
        subjects = data_service.discover_subjects()

        # Calculate stats
        total_subjects = len(subjects)
        total_subtopics = 0
        total_lessons = 0
        total_questions = 0

        for subject_id in subjects.keys():
            try:
                subject_config = data_service.load_subject_config(subject_id)
                if subject_config and "subtopics" in subject_config:
                    subtopics = subject_config["subtopics"]
                    total_subtopics += len(subtopics)

                    for subtopic_id, subtopic_data in subtopics.items():
                        total_lessons += subtopic_data.get("lesson_count", 0)
                        total_questions += subtopic_data.get("question_count", 0)
            except Exception as e:
                print(f"Error loading stats for subject {subject_id}: {e}")

        stats = {
            "total_subjects": total_subjects,
            "total_subtopics": total_subtopics,
            "total_lessons": total_lessons,
            "total_questions": total_questions,
        }

        return render_template("admin/dashboard.html", subjects=subjects, stats=stats)
    except Exception as e:
        print(f"Error loading admin dashboard: {e}")
        return f"Error loading admin dashboard: {e}", 500


@admin_bp.route("/student-data")
def admin_student_data():
    """Admin view for anonymized student attempts/cycles data."""
    try:
        anon_count = AnonUser.query.count()
        attempt_count = Attempt.query.count()
        cycle_count = Cycle.query.count()

        avg_score = (
            db.session.query(func.avg(Cycle.score_percent)).scalar() or 0
        )
        pass_count = Cycle.query.filter_by(passed_threshold=True).count()
        pass_rate = (pass_count / cycle_count * 100) if cycle_count else 0

        recent_attempts = (
            Attempt.query.order_by(Attempt.started_at.desc()).limit(50).all()
        )
        recent_cycles = (
            Cycle.query.order_by(Cycle.quiz_submitted_at.desc()).limit(50).all()
        )

        stats = {
            "anon_users": anon_count,
            "attempts": attempt_count,
            "cycles": cycle_count,
            "avg_score": round(float(avg_score), 2),
            "pass_rate": round(float(pass_rate), 2),
        }

        attempt_lookup = {attempt.attempt_id: attempt for attempt in recent_attempts}

        return render_template(
            "admin/student_data.html",
            stats=stats,
            recent_attempts=recent_attempts,
            recent_cycles=recent_cycles,
            attempt_lookup=attempt_lookup,
        )
    except Exception as e:
        print(f"Error loading student data overview: {e}")
        return (
            render_template("admin/student_data.html", error=str(e)),
            500,
        )


# ============================================================================
# ADMIN ACCOUNT MANAGEMENT
# ============================================================================


@admin_bp.route("/admins", methods=["GET"])
def admin_list_admins():
    """Return available teacher accounts and current admins."""
    try:
        user_service = get_user_service()
        current_user_id = session.get("user_id")
        current_user = (
            user_service.get_user(current_user_id) if current_user_id else None
        )
        can_manage_admins = user_service.is_super_admin_user(current_user)
        super_admin = User.query.filter_by(username="admin").first()
        super_admin_id = super_admin.id if super_admin else None
        teachers = (
            User.query.filter_by(role="teacher")
            .order_by(User.username.asc())
            .all()
        )

        admin_entries = []
        teacher_entries = []

        for teacher in teachers:
            entry = {
                "id": teacher.id,
                "username": teacher.username,
                "email": teacher.email,
            }
            if user_service.is_admin_user(teacher):
                admin_entries.append(entry)
            else:
                teacher_entries.append(entry)

        admin_entries.sort(key=lambda item: (item.get("username") or "").lower())
        teacher_entries.sort(key=lambda item: (item.get("username") or "").lower())

        return jsonify(
            {
                "success": True,
                "admins": admin_entries,
                "teachers": teacher_entries,
                "can_manage_admins": can_manage_admins,
                "current_user_id": current_user_id,
                "super_admin_id": super_admin_id,
            }
        )
    except Exception as exc:
        print(f"Error loading admin candidates: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@admin_bp.route("/admins/grant", methods=["POST"])
def admin_grant_admin():
    """Grant admin access to an existing teacher account."""
    try:
        payload = request.get_json(silent=True) or {}
        teacher_id = payload.get("teacher_id")
        try:
            teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "Teacher ID is required."}),
                400,
            )

        teacher = User.query.get(teacher_id)
        if not teacher or teacher.role != "teacher":
            return (
                jsonify({"success": False, "error": "Teacher account not found."}),
                404,
            )

        user_service = get_user_service()
        if user_service.is_admin_user(teacher):
            return jsonify(
                {
                    "success": True,
                    "message": f"{teacher.username} already has admin access.",
                }
            )

        if not user_service.grant_admin_access(teacher.id):
            return (
                jsonify({"success": False, "error": "Unable to grant admin access."}),
                500,
            )

        return jsonify(
            {
                "success": True,
                "message": f"{teacher.username} now has admin access.",
                "admin": {
                    "id": teacher.id,
                    "username": teacher.username,
                    "email": teacher.email,
                },
            }
        )
    except Exception as exc:
        print(f"Error granting admin access: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@admin_bp.route("/admins/revoke", methods=["POST"])
def admin_revoke_admin():
    """Revoke admin access (super admin only)."""
    try:
        payload = request.get_json(silent=True) or {}
        admin_id = payload.get("admin_id")
        try:
            admin_id = int(admin_id)
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "Admin ID is required."}),
                400,
            )

        user_service = get_user_service()
        current_user_id = session.get("user_id")
        current_user = (
            user_service.get_user(current_user_id) if current_user_id else None
        )

        if not user_service.is_super_admin_user(current_user):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Only the original admin can remove admin access.",
                    }
                ),
                403,
            )

        if current_user_id and admin_id == current_user_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "You cannot remove your own admin access.",
                    }
                ),
                400,
            )

        target_user = User.query.get(admin_id)
        if not target_user or target_user.role != "teacher":
            return (
                jsonify({"success": False, "error": "Admin account not found."}),
                404,
            )

        if user_service.is_super_admin_user(target_user):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "The original admin cannot be removed.",
                    }
                ),
                400,
            )

        if not user_service.is_admin_user(target_user):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "User does not have admin access.",
                    }
                ),
                400,
            )

        if not user_service.revoke_admin_access(admin_id):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Unable to remove admin access.",
                    }
                ),
                500,
            )

        return jsonify(
            {
                "success": True,
                "message": f"Admin access removed for {target_user.username}.",
            }
        )
    except Exception as exc:
        print(f"Error revoking admin access: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@admin_bp.route("/admins/create", methods=["POST"])
def admin_create_admin():
    """Create a new admin account."""
    try:
        payload = request.get_json(silent=True) or {}
        username = (payload.get("username") or "").strip()
        email = (payload.get("email") or "").strip()
        password = payload.get("password") or ""

        if not username or not email or not password:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Username, email, and password are required.",
                    }
                ),
                400,
            )

        user_service = get_user_service()
        result = user_service.register_user(username, email, password, "teacher")
        if not result.get("success"):
            return jsonify(result), 400

        user = result.get("user")
        if not user or not user_service.grant_admin_access(user.id):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Account created but admin access could not be granted.",
                    }
                ),
                500,
            )

        return jsonify(
            {
                "success": True,
                "message": f"{user.username} created with admin access.",
                "admin": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            }
        )
    except Exception as exc:
        print(f"Error creating admin: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@admin_bp.route("/overview/lessons")
def admin_overview_lessons():
    """Display all lessons across subjects and subtopics."""

    try:
        admin_service = get_admin_service()
        overview = admin_service.get_lessons_overview()

        if not overview.get("success", False):
            return render_template(
                "admin/all_lessons.html",
                subjects=[],
                stats={},
                error=overview.get("error", "Unable to load lessons overview"),
            )

        stats = dict(overview.get("stats", {}))
        subjects: List[Dict[str, Any]] = []

        for subject_id, subject_data in overview.get("subjects", {}).items():
            subtopics_data: List[Dict[str, Any]] = []

            for subtopic in subject_data.get("subtopics", []):
                lessons = subtopic.get("lessons", [])

                subtopics_data.append(
                    {
                        "id": subtopic.get("id"),
                        "name": subtopic.get(
                            "name",
                            (subtopic.get("id") or "").replace("_", " ").title(),
                        ),
                        "description": subtopic.get("description", ""),
                        "order": subtopic.get("order", 0),
                        "status": subtopic.get("status", "active"),
                        "estimated_time": subtopic.get("estimated_time", ""),
                        "prerequisites": subtopic.get("prerequisites", []),
                        "video_count": subtopic.get("video_count", 0),
                        "lesson_count": subtopic.get("lesson_count", len(lessons)),
                        "lessons": lessons,
                    }
                )

            subtopics_data.sort(
                key=lambda item: (item.get("order", 0), item.get("name", "").lower())
            )

            subjects.append(
                {
                    "id": subject_id,
                    "name": subject_data.get("name", subject_id.title()),
                    "description": subject_data.get("description", ""),
                    "icon": subject_data.get("icon", "fas fa-book"),
                    "color": subject_data.get("color", "#4a5568"),
                    "lesson_count": subject_data.get("lesson_count", 0),
                    "subtopics": subtopics_data,
                }
            )

        subjects.sort(key=lambda item: item.get("name", "").lower())

        stats.setdefault(
            "subjects_with_lessons",
            sum(1 for subject in subjects if subject.get("lesson_count", 0) > 0),
        )
        stats.setdefault(
            "subtopics_with_lessons",
            sum(
                1
                for subject in subjects
                for subtopic in subject.get("subtopics", [])
                if subtopic.get("lesson_count", 0) > 0
            ),
        )
        stats.setdefault(
            "total_lessons",
            sum(
                subtopic.get("lesson_count", 0)
                for subject in subjects
                for subtopic in subject.get("subtopics", [])
            ),
        )

        return render_template(
            "admin/all_lessons.html",
            subjects=subjects,
            stats=stats,
            error=None,
        )

    except Exception as exc:
        print(f"Error loading lessons overview: {exc}")
        return (
            render_template(
                "admin/all_lessons.html",
                subjects=[],
                stats={},
                error=str(exc),
            ),
            500,
        )


@admin_bp.route("/overview/questions")
def admin_overview_questions():
    """Display all questions across subjects and subtopics."""

    try:
        admin_service = get_admin_service()
        overview = admin_service.get_questions_overview()

        if not overview.get("success", False):
            return render_template(
                "admin/all_questions.html",
                subjects=[],
                stats={},
                error=overview.get("error", "Unable to load questions overview"),
            )

        stats = dict(overview.get("stats", {}))
        stats["total_questions"] = stats.get("total_initial_questions", 0) + stats.get(
            "total_pool_questions", 0
        )

        subjects = []
        for subject_id, subject_data in overview.get("subjects", {}).items():
            subtopics = []
            total_initial = 0
            total_pool = 0

            for subtopic in subject_data.get("subtopics", []):
                quiz_count = subtopic.get("quiz_questions_count", 0) or 0
                pool_count = subtopic.get("pool_questions_count", 0) or 0
                total_initial += quiz_count
                total_pool += pool_count

                subtopics.append(
                    {
                        **subtopic,
                        "total_questions": quiz_count + pool_count,
                    }
                )

            subjects.append(
                {
                    "id": subject_id,
                    "name": subject_data.get("name", subject_id.title()),
                    "description": subject_data.get("description", ""),
                    "icon": subject_data.get("icon", "fas fa-book"),
                    "color": subject_data.get("color", "#4a5568"),
                    "subtopics": subtopics,
                    "initial_count": total_initial,
                    "pool_count": total_pool,
                }
            )

        subjects.sort(key=lambda item: item["name"].lower())

        return render_template(
            "admin/all_questions.html",
            subjects=subjects,
            stats=stats,
            error=None,
        )

    except Exception as exc:
        print(f"Error loading questions overview: {exc}")
        return (
            render_template(
                "admin/all_questions.html",
                subjects=[],
                stats={},
                error=str(exc),
            ),
            500,
        )


@admin_bp.route("/overview/subtopics")
def admin_overview_subtopics():
    """Display all subtopics with lesson and question coverage."""

    try:
        admin_service = get_admin_service()
        overview = admin_service.get_subtopics_overview()

        if not overview.get("success", False):
            return render_template(
                "admin/all_subtopics.html",
                subjects=[],
                stats={},
                error=overview.get("error", "Unable to load subtopics overview"),
            )

        stats = dict(overview.get("stats", {}))
        stats["total_questions"] = stats.get("total_initial_questions", 0) + stats.get(
            "total_pool_questions", 0
        )

        subjects = []
        for subject_id, subject_data in overview.get("subjects", {}).items():
            subtopics = []
            lesson_ready = 0
            question_ready = 0

            for subtopic in subject_data.get("subtopics", []):
                lesson_count = subtopic.get("lesson_count", 0) or 0
                total_questions = (subtopic.get("quiz_questions_count", 0) or 0) + (
                    subtopic.get("pool_questions_count", 0) or 0
                )

                if lesson_count > 0:
                    lesson_ready += 1
                if total_questions > 0:
                    question_ready += 1

                subtopics.append(
                    {
                        **subtopic,
                        "total_questions": total_questions,
                        "has_lessons": lesson_count > 0,
                        "has_questions": total_questions > 0,
                    }
                )

            subjects.append(
                {
                    "id": subject_id,
                    "name": subject_data.get("name", subject_id.title()),
                    "description": subject_data.get("description", ""),
                    "icon": subject_data.get("icon", "fas fa-book"),
                    "color": subject_data.get("color", "#4a5568"),
                    "subtopics": subtopics,
                    "lesson_ready_count": lesson_ready,
                    "question_ready_count": question_ready,
                }
            )

        subjects.sort(key=lambda item: item["name"].lower())

        return render_template(
            "admin/all_subtopics.html",
            subjects=subjects,
            stats=stats,
            error=None,
        )

    except Exception as exc:
        print(f"Error loading subtopics overview: {exc}")
        return (
            render_template(
                "admin/all_subtopics.html",
                subjects=[],
                stats={},
                error=str(exc),
            ),
            500,
        )


# ============================================================================
# SUBJECT MANAGEMENT ROUTES
# ============================================================================


@admin_bp.route("/subjects")
def admin_subjects():
    """Manage subjects."""
    try:
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        return render_template("admin/subjects.html", subjects=subjects)
    except Exception as e:
        print(f"Error loading subjects admin: {e}")
        return f"Error loading subjects: {e}", 500


@admin_bp.route("/subjects/create", methods=["GET", "POST"])
def admin_create_subject():
    """Create a new subject."""
    try:
        admin_service = get_admin_service()

        if request.method == "POST":
            data = request.get_json()
            result = admin_service.create_subject(data)

            if result["success"]:
                return jsonify(result)
            else:
                return jsonify(result), 400

        # GET request - show create form
        return render_template("admin/create_subject.html")

    except Exception as e:
        print(f"Error in create subject: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/subjects/<subject>/edit")
def admin_edit_subject(subject):
    """Edit a subject."""
    try:
        data_service = get_data_service()

        # Load subject data
        subject_info = data_service.load_subject_info(subject)
        subject_config = data_service.load_subject_config(subject)

        if not subject_info or not subject_config:
            return f"Subject '{subject}' not found", 404

        # Combine config and info into the expected structure (like original app.py)
        config = {
            "subject_info": subject_info,
            "subtopics": subject_config.get("subtopics", {}),
            "allowed_tags": subject_config.get("allowed_tags", []),
        }

        return render_template(
            "admin/edit_subject.html", subject=subject, config=config
        )

    except Exception as e:
        print(f"Error loading subject for editing: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/subjects/<subject>/update", methods=["POST"])
def admin_update_subject(subject):
    """Update a subject's configuration."""
    try:
        data = request.get_json() or {}

        admin_service = get_admin_service()
        result = admin_service.update_subject(subject, data)
        status_code = result.pop("status", 200 if result.get("success") else 400)

        return jsonify(result), status_code

    except Exception as e:
        print(f"Error updating subject {subject}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/subjects/<subject>/<subtopic>")
def admin_edit_subtopic(subject, subtopic):
    """Edit a subtopic."""
    try:
        data_service = get_data_service()

        # Load subject config to validate subtopic exists in configuration
        subject_config = data_service.load_subject_config(subject)
        if not subject_config or subtopic not in subject_config.get("subtopics", {}):
            return f"Subject '{subject}' with subtopic '{subtopic}' not found", 404

        return redirect(
            url_for(
                "admin.admin_subtopics",
                subject=subject,
                subtopic=subtopic,
                action="edit",
            )
        )

    except Exception as e:
        print(f"Error loading subtopic for editing: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/subjects/<subject>/delete", methods=["DELETE"])
def admin_delete_subject(subject):
    """Delete a subject."""
    try:
        admin_service = get_admin_service()
        result = admin_service.delete_subject(subject)

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        print(f"Error deleting subject: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# LESSON MANAGEMENT ROUTES
# ============================================================================


@admin_bp.route("/lessons")
def admin_lessons():
    """List lessons for a specific subject/subtopic with drag-to-reorder functionality."""
    try:
        data_service = get_data_service()

        # Get URL parameters for filtering
        subject_filter = request.args.get("subject")
        subtopic_filter = request.args.get("subtopic")

        # Require both subject and subtopic for the drag-to-reorder view
        if not subject_filter or not subtopic_filter:
            # Redirect to subject selection if parameters are missing
            return redirect(url_for("admin.admin_select_subject_for_lessons"))

        # Use auto-discovery for subjects dropdown
        subjects = data_service.discover_subjects()

        # Validate subject exists
        if subject_filter not in subjects:
            return f"Subject '{subject_filter}' not found", 404

        # Get subject config to validate subtopic exists in configuration
        subject_config = data_service.load_subject_config(subject_filter)
        if not subject_config or subtopic_filter not in subject_config.get(
            "subtopics", {}
        ):
            return (
                f"Subject '{subject_filter}' with subtopic '{subtopic_filter}' not found",
                404,
            )

        # Load lessons for this specific subject/subtopic
        lessons = data_service.get_lesson_map(subject_filter, subtopic_filter)

        # Sort lessons by order field for display
        sorted_lessons = dict(
            sorted(
                lessons.items(),
                key=lambda x: (
                    x[1].get("order", 999),
                    x[0],
                ),  # Sort by order, then by lesson_id
            )
        )

        # Get subject info
        subject_info = subjects[subject_filter]
        subject_name = subject_info.get("name", subject_filter.title())

        # Get subtopic info
        subject_config = data_service.load_subject_config(subject_filter)
        subtopic_name = None
        if subject_config and "subtopics" in subject_config:
            subtopics = subject_config["subtopics"]
            if subtopic_filter in subtopics:
                subtopic_name = subtopics[subtopic_filter].get(
                    "name", subtopic_filter.title()
                )

        if not subtopic_name:
            subtopic_name = subtopic_filter.title()

        return render_template(
            "admin/lessons.html",
            lessons=sorted_lessons,
            subjects=subjects,
            subject_filter=subject_filter,
            subtopic_filter=subtopic_filter,
            subject_name=subject_name,
            subtopic_name=subtopic_name,
            subject_info=subject_info,
            filtered_view=True,
            subject=subject_filter,
            subtopic=subtopic_filter,
        )
    except Exception as e:
        print(f"Error loading lessons: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/lessons/create", methods=["GET", "POST"])
def admin_create_lesson():
    """Create a new lesson."""
    try:
        admin_service = get_admin_service()

        if request.method == "POST":
            data = request.get_json()
            result = admin_service.create_lesson(data)

            if result["success"]:
                return jsonify(result)
            else:
                return jsonify(result), 400

        # GET request - show create form
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        return render_template("admin/create_lesson.html", subjects=subjects)

    except Exception as e:
        print(f"Error in create lesson: {e}")
        return f"Error: {e}", 500


@admin_bp.route(
    "/lessons/<subject>/<subtopic>/<lesson_id>/edit", methods=["GET", "POST"]
)
def admin_edit_lesson(subject, subtopic, lesson_id):
    """Edit an existing lesson."""
    if request.method == "POST":
        try:
            data = request.json
            lesson_title = data.get("title", "")
            video_id = data.get("videoId", "")
            content = data.get("content", [])
            tags = data.get("tags", [])
            lesson_type = (
                (data.get("lessonType") or data.get("type")).strip().lower()
                if (data.get("lessonType") or data.get("type"))
                else None
            )
            # Get the new lesson ID (may be different from the URL param)
            new_lesson_id = data.get("id", lesson_id)

            # Get order if provided
            order = data.get("order")
            order_provided = order is not None

            if not lesson_title:
                return jsonify({"error": "Lesson title is required"}), 400

            data_service = get_data_service()
            admin_service = get_admin_service()

            # Load existing to preserve fields not provided
            existing_lessons = data_service.get_lesson_map(subject, subtopic)
            existing = existing_lessons.get(lesson_id, {})
            if lesson_type is None:
                lesson_type = existing.get("type", "remedial")

            lesson_data = {
                **existing,
                "id": new_lesson_id,  # Use the new ID
                "title": lesson_title,
                "videoId": video_id,
                "content": content,
                "tags": tags,
                "type": lesson_type,
            }

            # Only include order if it was provided (not None)
            if order is not None:
                lesson_data["order"] = order

            result = admin_service.update_lesson(
                subject,
                subtopic,
                lesson_id,
                lesson_data,
                order_provided=order_provided,
            )

            if result.get("success"):
                # If ID was changed, include the new ID in the response
                if result.get("id_changed"):
                    result["new_lesson_id"] = result.get("new_lesson_id")
                return jsonify(result)

            return jsonify(result), 400

        except Exception as e:
            print(f"Error updating lesson: {e}")
            return jsonify({"error": str(e)}), 500

    # GET request - show edit form
    try:
        data_service = get_data_service()
        lesson_map = data_service.get_lesson_map(subject, subtopic)

        # Load existing lesson
        if lesson_id not in lesson_map:
            return f"Lesson '{lesson_id}' not found", 404

        lesson_data = lesson_map[lesson_id]

        # Get subjects for context
        subjects = data_service.discover_subjects()

        # Load subtopics for the current subject (needed for edit mode)
        subject_config = data_service.load_subject_config(subject)
        subject_subtopics = (
            subject_config.get("subtopics", {}) if subject_config else {}
        )

        return render_template(
            "admin/create_lesson.html",
            subjects=subjects,
            edit_mode=True,
            subject=subject,
            subtopic=subtopic,
            lesson_id=lesson_id,
            lesson_data=lesson_data,
            subject_subtopics=subject_subtopics,
        )
    except Exception as e:
        print(f"Error loading lesson editor: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/lessons/<subject>/<subtopic>/<lesson_id>/delete", methods=["DELETE"])
def admin_delete_lesson(subject, subtopic, lesson_id):
    """Delete a lesson."""
    try:
        admin_service = get_admin_service()
        result = admin_service.delete_lesson(subject, subtopic, lesson_id)

        if result.get("success"):
            return jsonify(result)

        error_message = result.get("error", "Lesson not found or could not be deleted")
        status_code = 404 if "not found" in error_message.lower() else 400
        return jsonify(result), status_code

    except Exception as e:
        print(f"Error deleting lesson: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/lessons/<subject>/<subtopic>/reorder", methods=["POST"])
def admin_reorder_lessons(subject, subtopic):
    """Reorder lessons in a subtopic."""
    try:
        admin_service = get_admin_service()
        data = request.get_json()

        result = admin_service.reorder_lessons(subject, subtopic, data)

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        print(f"Error reordering lessons: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/lessons/select-subject")
def admin_select_subject_for_lessons():
    """Select subject for lesson management."""
    try:
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        return render_template("admin/select_subject_lessons.html", subjects=subjects)
    except Exception as e:
        print(f"Error loading subject selection: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/lessons/select-subtopic")
def admin_select_subtopic_for_lessons():
    """Select subtopic for lesson management."""
    try:
        subject = request.args.get("subject")
        if not subject:
            return redirect(url_for("admin.admin_select_subject_for_lessons"))

        data_service = get_data_service()
        subject_config = data_service.load_subject_config(subject)
        subtopics = subject_config.get("subtopics", {}) if subject_config else {}

        return render_template(
            "admin/select_subtopic_lessons.html", subject=subject, subtopics=subtopics
        )
    except Exception as e:
        print(f"Error loading subtopic selection: {e}")
        return f"Error: {e}", 500


# ============================================================================
# QUESTIONS AND QUIZ MANAGEMENT
# ============================================================================


@admin_bp.route("/questions")
def admin_questions():
    """Questions management page."""
    try:
        data_service = get_data_service()
        data_loader = data_service.data_loader

        # Get URL parameters for filtering
        subject_filter = request.args.get("subject")
        subtopic_filter = request.args.get("subtopic")

        # Use auto-discovery instead of subjects.json
        subjects_data = {}
        stats = {
            "total_initial_questions": 0,
            "total_pool_questions": 0,
            "total_subtopics": 0,
            "subtopics_without_questions": 0,
        }

        # Discover subjects using auto-discovery
        discovered_subjects = data_loader.discover_subjects()

        # Get subject and subtopic names for display
        subject_name = None
        subtopic_name = None

        if subject_filter and subject_filter in discovered_subjects:
            subject_name = discovered_subjects[subject_filter].get(
                "name", subject_filter.title()
            )

            if subtopic_filter:
                subject_config = data_loader.load_subject_config(subject_filter)
                if subject_config and "subtopics" in subject_config:
                    subtopics = subject_config["subtopics"]
                    if subtopic_filter in subtopics:
                        subtopic_name = subtopics[subtopic_filter].get(
                            "name", subtopic_filter.title()
                        )

        for subject_id, subject_info in discovered_subjects.items():
            # Skip if we're filtering by subject and this isn't the one
            if subject_filter and subject_id != subject_filter:
                continue

            # Load subject config to get subtopics
            subject_config = data_loader.load_subject_config(subject_id)
            if subject_config and "subtopics" in subject_config:
                subject_data = {
                    "name": subject_info.get("name", subject_id),
                    "description": subject_info.get("description", ""),
                    "subtopics": {},
                }

                for subtopic_id, subtopic_data in subject_config["subtopics"].items():
                    # Skip if we're filtering by subtopic and this isn't the one
                    if subtopic_filter and subtopic_id != subtopic_filter:
                        continue

                    # Load quiz data and question pool to get counts
                    quiz_data = data_loader.load_quiz_data(subject_id, subtopic_id)
                    pool_data = data_loader.get_question_pool_questions(
                        subject_id, subtopic_id
                    )

                    quiz_count = len(quiz_data.get("questions", [])) if quiz_data else 0
                    pool_count = len(pool_data) if pool_data else 0

                    subtopic_data["quiz_questions_count"] = quiz_count
                    subtopic_data["pool_questions_count"] = pool_count

                    # Update statistics
                    stats["total_initial_questions"] += quiz_count
                    stats["total_pool_questions"] += pool_count
                    stats["total_subtopics"] += 1

                    if quiz_count == 0 and pool_count == 0:
                        stats["subtopics_without_questions"] += 1

                    subject_data["subtopics"][subtopic_id] = subtopic_data

                subjects_data[subject_id] = subject_data

        return render_template(
            "admin/questions.html",
            subjects=subjects_data,
            stats=stats,
            subject_filter=subject_filter,
            subtopic_filter=subtopic_filter,
            subject_name=subject_name,
            subtopic_name=subtopic_name,
        )

    except Exception as e:
        print(f"Error loading questions admin page: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/questions/select-subject")
def admin_select_subject_for_questions():
    """Select subject for questions management."""
    try:
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        return render_template("admin/select_subject_questions.html", subjects=subjects)
    except Exception as e:
        print(f"Error loading subject selection: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/questions/select-subtopic")
def admin_select_subtopic_for_questions():
    """Select subtopic for questions management."""
    try:
        subject = request.args.get("subject")
        if not subject:
            return redirect(url_for("admin.admin_select_subject_for_questions"))

        data_service = get_data_service()
        subject_config = data_service.load_subject_config(subject)
        subtopics = subject_config.get("subtopics", {}) if subject_config else {}

        return render_template(
            "admin/select_subtopic_questions.html", subject=subject, subtopics=subtopics
        )
    except Exception as e:
        print(f"Error loading subtopic selection: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/quiz/<subject>/<subtopic>")
def admin_quiz_editor(subject, subtopic):
    """Quiz editor page for a specific subject/subtopic."""
    try:
        from utils.data_loader import DataLoader

        data_loader = DataLoader("data")

        # First, check if the subject exists and the subtopic is defined in subject config
        subject_config = data_loader.load_subject_config(subject)
        if not subject_config:
            return f"Subject '{subject}' not found", 404

        # Check if subtopic exists in configuration
        if subtopic not in subject_config.get("subtopics", {}):
            return f"Subtopic '{subtopic}' not found in subject '{subject}'", 404

        # Check if files exist, if not we'll handle empty state gracefully
        files_exist = data_loader.validate_subject_subtopic(subject, subtopic)

        # Load quiz data and question pool (will be None if files don't exist)
        quiz_data = data_loader.load_quiz_data(subject, subtopic)
        pool_questions = data_loader.get_question_pool_questions(subject, subtopic)

        # If no data exists, create empty structures
        if not quiz_data:
            quiz_data = {"questions": []}
        if not pool_questions:
            pool_questions = []

        # Format question pool to match template expectations
        question_pool = {"questions": pool_questions}

        # Get subject and subtopic info for display
        subject_info = subject_config.get("subject_info", {})
        subtopic_info = subject_config["subtopics"][subtopic]

        return render_template(
            "admin/quiz_editor.html",
            subject=subject,
            subtopic=subtopic,
            subject_info=subject_info,
            subtopic_info=subtopic_info,
            quiz_data=quiz_data,
            question_pool=question_pool,
            files_exist=files_exist,
        )
    except Exception as e:
        print(f"Error loading quiz editor: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/quiz/<subject>/<subtopic>/initial", methods=["GET", "POST"])
def admin_quiz_initial(subject, subtopic):
    """Manage initial quiz questions."""
    data_service = get_data_service()
    data_loader = data_service.data_loader

    if request.method == "GET":
        try:
            quiz_data = data_loader.load_quiz_data(subject, subtopic)
            return jsonify(quiz_data if quiz_data else {"questions": []})
        except Exception as e:
            print(f"Error loading initial quiz data: {e}")
            return jsonify({"error": str(e)}), 500

    elif request.method == "POST":
        try:
            data = request.json
            questions = data.get("questions", [])

            # Create quiz data structure
            quiz_data = {
                "quiz_title": f"{subject.title()} - {subtopic.title()} Quiz",
                "questions": questions,
                "updated_date": "2025-01-01",
            }

            # Save to file
            quiz_file_path = os.path.join(
                data_service.data_root_path,
                "subjects",
                subject,
                subtopic,
                "quiz_data.json",
            )

            # Ensure directory exists
            os.makedirs(os.path.dirname(quiz_file_path), exist_ok=True)

            with open(quiz_file_path, "w", encoding="utf-8") as f:
                json.dump(quiz_data, f, indent=2)

            # Clear cache for this subject/subtopic to ensure fresh data is loaded
            data_service.clear_cache_for_subject_subtopic(subject, subtopic)
            print(f"Cleared cache for {subject}/{subtopic} after updating quiz data")

            return jsonify(
                {"success": True, "message": "Initial quiz updated successfully"}
            )

        except Exception as e:
            print(f"Error updating initial quiz: {e}")
            return jsonify({"error": str(e)}), 500


@admin_bp.route("/quiz/<subject>/<subtopic>/pool", methods=["GET", "POST"])
def admin_quiz_pool(subject, subtopic):
    """Manage question pool for remedial quizzes."""
    data_service = get_data_service()
    data_loader = data_service.data_loader

    if request.method == "GET":
        try:
            pool_data = data_loader.get_question_pool_questions(subject, subtopic)
            return jsonify({"questions": pool_data if pool_data else []})
        except Exception as e:
            print(f"Error loading question pool: {e}")
            return jsonify({"error": str(e)}), 500

    elif request.method == "POST":
        try:
            data = request.json
            questions = data.get("questions", [])

            # Create question pool structure
            pool_data = {
                "pool_title": f"{subject.title()} - {subtopic.title()} Question Pool",
                "questions": questions,
                "updated_date": "2025-01-01",
            }

            # Save to file
            pool_file_path = os.path.join(
                data_service.data_root_path,
                "subjects",
                subject,
                subtopic,
                "question_pool.json",
            )

            # Ensure directory exists
            os.makedirs(os.path.dirname(pool_file_path), exist_ok=True)

            with open(pool_file_path, "w", encoding="utf-8") as f:
                json.dump(pool_data, f, indent=2)

            # Clear cache for this subject/subtopic to ensure fresh data is loaded
            data_service.clear_cache_for_subject_subtopic(subject, subtopic)
            print(
                f"Cleared cache for {subject}/{subtopic} after updating question pool"
            )

            return jsonify(
                {"success": True, "message": "Question pool updated successfully"}
            )

        except Exception as e:
            print(f"Error updating question pool: {e}")
            return jsonify({"error": str(e)}), 500


# ============================================================================
# SUBTOPICS MANAGEMENT
# ============================================================================


@admin_bp.route("/subtopics/select-subject")
def admin_select_subject_for_subtopics():
    """Select subject for subtopics management."""
    try:
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        return render_template("admin/select_subject_subtopics.html", subjects=subjects)
    except Exception as e:
        print(f"Error loading subject selection: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/subtopics")
def admin_subtopics():
    """Manage subtopics for a specific subject with drag-to-reorder functionality."""
    try:
        data_service = get_data_service()
        data_loader = data_service.data_loader

        # Get URL parameters for filtering
        subject_filter = request.args.get("subject")

        # Require subject for the drag-to-reorder view
        if not subject_filter:
            # Redirect to subject selection if parameter is missing
            return redirect(url_for("admin.admin_select_subject_for_subtopics"))

        # Use auto-discovery for subjects dropdown
        subjects = data_loader.discover_subjects()

        # Validate subject exists
        if subject_filter not in subjects:
            return f"Subject '{subject_filter}' not found", 404

        # Load subject configuration
        subject_config = data_loader.load_subject_config(subject_filter)
        if not subject_config:
            return f"Subject configuration for '{subject_filter}' not found", 404

        # Get subject info
        subject_info = subjects[subject_filter]
        subject_name = subject_info.get("name", subject_filter.title())

        # Get subtopics from subject config
        subtopics = subject_config.get("subtopics", {})
        allowed_tags = subject_config.get(
            "allowed_tags", subject_config.get("allowed_keywords", [])
        )

        return render_template(
            "admin/subtopics.html",
            subjects=subjects,
            subject_filter=subject_filter,
            subject_name=subject_name,
            subject_info=subject_info,
            subtopics=subtopics,
            allowed_tags=allowed_tags,
            filtered_view=True,
            subject=subject_filter,
        )
    except Exception as e:
        print(f"Error loading subtopics: {e}")
        return f"Error: {e}", 500


@admin_bp.route("/subtopics/<subject>/reorder", methods=["POST"])
def admin_reorder_subtopics(subject):
    """Reorder subtopics for a subject."""
    try:
        data_service = get_data_service()
        data_loader = data_service.data_loader

        # Get the new order from request
        new_order = request.json.get("order", [])

        if not new_order:
            return jsonify({"success": False, "error": "No order provided"}), 400

        # Load current subject config
        subject_config = data_loader.load_subject_config(subject)
        if not subject_config:
            return jsonify({"success": False, "error": "Subject config not found"}), 404

        # Get current subtopics
        current_subtopics = subject_config.get("subtopics", {})

        # Validate all subtopics in new order exist
        for subtopic_id in new_order:
            if subtopic_id not in current_subtopics:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Subtopic '{subtopic_id}' not found",
                        }
                    ),
                    400,
                )

        # Create reordered subtopics dict
        reordered_subtopics = {}
        seen_subtopics = set()
        next_position = 1

        for subtopic_id in new_order:
            subtopic_data = current_subtopics[subtopic_id]
            if isinstance(subtopic_data, dict):
                updated_data = dict(subtopic_data)
                updated_data["order"] = next_position
            else:
                updated_data = subtopic_data

            reordered_subtopics[subtopic_id] = updated_data
            seen_subtopics.add(subtopic_id)
            next_position += 1

        # Add any subtopics not in the new order (shouldn't happen, but safety)
        for subtopic_id, subtopic_data in current_subtopics.items():
            if subtopic_id in seen_subtopics:
                continue

            if isinstance(subtopic_data, dict):
                updated_data = dict(subtopic_data)
                updated_data["order"] = next_position
            else:
                updated_data = subtopic_data

            reordered_subtopics[subtopic_id] = updated_data
            next_position += 1

        # Update subject config
        updated_config = dict(subject_config)
        updated_config["subtopics"] = reordered_subtopics

        # Save updated config
        config_file_path = os.path.join(
            data_service.data_root_path,
            "subjects",
            subject,
            "subject_config.json",
        )
        with open(config_file_path, "w", encoding="utf-8") as f:
            json.dump(updated_config, f, indent=2, ensure_ascii=False)

        # Clear cache
        data_service.clear_cache_for_subject(subject)

        return jsonify({"success": True, "message": "Subtopics reordered successfully"})

    except Exception as e:
        print(f"Error reordering subtopics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/subtopics/<subject>/<subtopic_id>/delete", methods=["DELETE"])
def admin_delete_subtopic(subject, subtopic_id):
    """Delete a subtopic."""
    try:
        admin_service = get_admin_service()
        result = admin_service.delete_subtopic(subject, subtopic_id)

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        print(f"Error deleting subtopic: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/subtopics/<subject>/<subtopic_id>/toggle-status", methods=["POST"])
def admin_toggle_subtopic_status(subject, subtopic_id):
    """Toggle subtopic status between active and inactive."""
    try:
        data_service = get_data_service()

        # Load subject config
        subject_config = data_service.load_subject_config(subject)
        if not subject_config:
            return jsonify({"success": False, "error": "Subject config not found"}), 404

        subtopics = subject_config.get("subtopics", {})
        if subtopic_id not in subtopics:
            return jsonify({"success": False, "error": "Subtopic not found"}), 404

        # Get current status and toggle
        subtopic_data = subtopics[subtopic_id]
        current_status = subtopic_data.get("status", "active")
        new_status = "inactive" if current_status == "active" else "active"

        # Update status
        subtopic_data["status"] = new_status
        subtopics[subtopic_id] = subtopic_data

        # Save to file
        config_path = os.path.join(
            data_service.data_root_path, "subjects", subject, "subject_config.json"
        )

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(subject_config, f, indent=2, ensure_ascii=False)

        # Clear cache
        data_service.clear_cache_for_subject(subject)

        return jsonify(
            {
                "success": True,
                "status": new_status,
                "message": f"Subtopic status changed to {new_status}",
            }
        )

    except Exception as e:
        print(f"Error toggling subtopic status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# EXPORT / IMPORT MANAGEMENT
# ============================================================================


@admin_bp.route("/export")
def admin_export_page():
    """Render the export/import dashboard."""
    try:
        data_service = get_data_service()
        loader = data_service.data_loader

        subjects = loader.discover_subjects()
        subject_stats = []
        total_subtopics = 0
        total_lessons = 0

        for subject_id, subject_meta in subjects.items():
            subject_name = subject_meta.get("name", subject_id.title())
            subject_color = subject_meta.get("color", "#2563eb")

            subject_config = loader.load_subject_config(subject_id) or {}
            subtopics_map = (
                subject_config.get("subtopics", {})
                if isinstance(subject_config, dict)
                else {}
            )

            subtopic_count = len(subtopics_map)
            lesson_count = 0

            for subtopic_id in subtopics_map.keys():
                lesson_data = loader.load_lesson_plans(subject_id, subtopic_id) or {}
                lessons = lesson_data.get("lessons", {})
                if isinstance(lessons, dict):
                    lesson_count += len(lessons)
                elif isinstance(lessons, list):
                    lesson_count += len(lessons)

            subject_stats.append(
                {
                    "id": subject_id,
                    "name": subject_name,
                    "subtopics": subtopic_count,
                    "lessons": lesson_count,
                    "color": subject_color,
                }
            )

            total_subtopics += subtopic_count
            total_lessons += lesson_count

        subject_stats.sort(key=lambda item: item["name"])

        return render_template(
            "admin/export.html",
            subject_stats=subject_stats,
            total_subjects=len(subject_stats),
            total_subtopics=total_subtopics,
            total_lessons=total_lessons,
        )

    except Exception as exc:
        print(f"Error loading export page: {exc}")
        return (
            render_template(
                "admin/export.html",
                subject_stats=[],
                total_subjects=0,
                total_subtopics=0,
                total_lessons=0,
                error=str(exc),
            ),
            500,
        )


@admin_bp.route("/export/download")
def admin_export_download():
    """Return a JSON export of all content as a downloadable file."""
    try:
        admin_service = get_admin_service()
        payload = admin_service.export_all_content()

        json_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

        response = Response(json_bytes, mimetype="application/json")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=self-paced-export-{timestamp}.json"
        )
        return response

    except Exception as exc:
        print(f"Error exporting data: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@admin_bp.route("/export/import", methods=["POST"])
def admin_import_data():
    """Accept a JSON snapshot and import it into the data directory."""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded."}), 400

        upload = request.files["file"]
        if upload.filename == "":
            return jsonify({"success": False, "error": "Empty filename provided."}), 400

        raw_bytes = upload.read()
        if not raw_bytes:
            return jsonify({"success": False, "error": "Uploaded file is empty."}), 400

        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as parse_exc:
            return (
                jsonify({"success": False, "error": f"Invalid JSON: {parse_exc}"}),
                400,
            )

        admin_service = get_admin_service()
        result = admin_service.import_all_content(payload)

        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code

    except Exception as exc:
        print(f"Error importing data: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


# ============================================================================
# CACHE AND UTILITIES
# ============================================================================


@admin_bp.route("/clear-cache", methods=["POST"])
def admin_clear_cache():
    """Clear all cached data."""
    try:
        data_service = get_data_service()
        data_service.clear_cache()
        return jsonify({"success": True, "message": "Cache cleared successfully"})
    except Exception as e:
        print(f"Failed to clear cache: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/maintenance/expire-attempts", methods=["POST"])
def admin_expire_attempts():
    """Expire stale attempts as abandoned."""
    try:
        timeout_minutes = int(request.args.get("timeout", "60"))
        from services import get_progress_service

        progress_service = get_progress_service()
        ended_count = progress_service.end_stale_attempts(timeout_minutes)
        return jsonify({"success": True, "ended": ended_count})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ============================================================================
# OVERRIDE AND TESTING FUNCTIONALITY
# ============================================================================


@admin_bp.route("/toggle-override", methods=["GET", "POST"])
def admin_toggle_override():
    """Toggle or check admin override status for debugging/testing."""
    try:
        admin_service = get_admin_service()

        if request.method == "POST":
            payload = request.get_json(silent=True) or {}

            if "enabled" in payload:
                result = admin_service.set_override(bool(payload.get("enabled")))
            else:
                result = admin_service.toggle_override()

            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        else:
            # Check current status
            override_status = admin_service.check_override_status()
            status_code = 200 if override_status.get("success") else 500
            return jsonify(override_status), status_code

    except Exception as e:
        print(f"Error in admin override: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
