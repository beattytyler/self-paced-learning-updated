"""Main Routes Blueprint

Handles core application routes including subject selection, quiz pages,
and primary user-facing functionality.
"""

import json
import re

from flask import (
    Blueprint,
    render_template,
    session,
    redirect,
    url_for,
    request,
    jsonify,
)
from services import get_data_service, get_progress_service, get_ai_service
from extensions import cache
from typing import Dict, List, Optional, Any, Set

# Create the Blueprint
main_bp = Blueprint("main", __name__)


@main_bp.before_request
def ensure_authenticated():
    """Redirect anonymous users to the login page."""
    if session.get("user_id"):
        return None

    # Allow public access to the subject selection landing page and auth routes
    allowed_endpoints = {
        "main.subject_selection",
        "auth.login",
        "auth.register",
        "static",
    }
    if request.endpoint in allowed_endpoints:
        return None

    return redirect(url_for("auth.login"))


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_quiz_data(subject: str, subtopic: str) -> Optional[List[Dict]]:
    """Load quiz questions for a specific subject/subtopic."""
    data_service = get_data_service()
    return data_service.data_loader.get_quiz_questions(subject, subtopic)


def get_lesson_plans(subject: str, subtopic: str) -> List[Dict]:
    """Load lesson plans for a specific subject/subtopic."""
    data_service = get_data_service()
    return data_service.get_lesson_plans(
        subject, subtopic, include_unlisted=False
    ) or []


def get_video_data(subject: str, subtopic: str) -> Optional[Dict]:
    """Load video data for a specific subject/subtopic."""
    data_service = get_data_service()
    if not data_service.videos_file_exists(subject, subtopic):
        return {"videos": []}
    videos_data = data_service.data_loader.load_videos(subject, subtopic)
    return videos_data.get("videos", {}) if videos_data else {}


def is_active_subtopic(subtopic_data: Dict[str, Any]) -> bool:
    """Return True when the subtopic is considered available to learners."""
    if not isinstance(subtopic_data, dict):
        return False
    status = subtopic_data.get("status")
    normalized = "" if status is None else str(status).strip().lower()
    return normalized in ("", "active")


def filter_active_subtopics(subtopics: Dict[str, Any]) -> Dict[str, Any]:
    """Filter subtopic map down to only active entries."""
    return {
        subtopic_id: subtopic_data
        for subtopic_id, subtopic_data in (subtopics or {}).items()
        if is_active_subtopic(subtopic_data)
    }


def normalize_tag_key(tag: str) -> str:
    """Normalize tag text for cross-file matching."""
    if not isinstance(tag, str):
        return ""
    cleaned = tag.strip().lower()
    cleaned = cleaned.replace("comparsion", "comparison")
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def expand_tag_keys(tag_value: Any) -> Set[str]:
    """Return normalized tag keys for matching, including split tokens."""
    if tag_value is None:
        return set()
    text = str(tag_value)
    parts = [text]
    if re.search(r"[,;/|+]", text):
        parts = re.split(r"[,;/|+]+", text)
    elif " " in text and "_" in text:
        parts = re.split(r"\s+", text)

    expanded_parts: List[str] = []
    for part in parts:
        if "(" in part and ")" in part:
            base = part.split("(", 1)[0].strip()
            if base:
                expanded_parts.append(base)
            inner = part[part.find("(") + 1 : part.find(")")]
            if inner:
                expanded_parts.append(inner.strip())

    if expanded_parts:
        parts.extend(expanded_parts)

    keys: Set[str] = set()
    full_key = normalize_tag_key(text)
    if full_key:
        keys.add(full_key)
    for part in parts:
        key = normalize_tag_key(part)
        if key:
            keys.add(key)
    return keys




# Cache key helpers (per-user to avoid leaking personalized data)
def _subject_selection_cache_key() -> str:
    user_id = session.get("user_id") or "anon"
    role = session.get("role") or "none"
    username = session.get("username") or "anon"
    is_admin = session.get("is_admin", False)
    return f"subject_selection:{user_id}:{role}:{username}:{int(bool(is_admin))}"

def _subject_page_cache_key() -> str:
    user_id = session.get("user_id") or "anon"
    role = session.get("role") or "none"
    username = session.get("username") or "anon"
    is_admin = session.get("is_admin", False)
    subject = (request.view_args or {}).get("subject", "")
    return f"subject_page:{subject}:{user_id}:{role}:{username}:{int(bool(is_admin))}"


# ============================================================================
# MAIN APPLICATION ROUTES
# ============================================================================


@main_bp.route("/")
@cache.cached(timeout=60, key_prefix=_subject_selection_cache_key)
def subject_selection():
    """New home page showing all available subjects."""
    try:
        data_service = get_data_service()
        subjects = data_service.discover_subjects()

        # Calculate stats for each subject
        for subject_id, subject_info in subjects.items():
            subject_config = data_service.load_subject_config(subject_id)

            if subject_config and "subtopics" in subject_config:
                subtopics = filter_active_subtopics(subject_config["subtopics"])
                total_lessons = 0
                total_videos = 0
                total_questions = 0

                for subtopic_id in subtopics.keys():
                    # Count lessons
                    lessons = get_lesson_plans(subject_id, subtopic_id)
                    total_lessons += len(lessons) if lessons else 0

                    # Count videos
                    videos = get_video_data(subject_id, subtopic_id)
                    if videos and "videos" in videos:
                        total_videos += len(videos["videos"])

                    # Count questions
                    quiz_data = get_quiz_data(subject_id, subtopic_id)
                    total_questions += len(quiz_data) if quiz_data else 0

                subject_info["stats"] = {
                    "lessons": total_lessons,
                    "videos": total_videos,
                    "questions": total_questions,
                    "subtopics": len(subtopics),
                }
            else:
                subject_info["stats"] = {
                    "lessons": 0,
                    "videos": 0,
                    "questions": 0,
                    "subtopics": 0,
                }

        user_role = session.get("role")
        username = session.get("username")
        is_admin = session.get("is_admin", False)

        return render_template(
            "subject_selection.html",
            subjects=subjects,
            user_role=user_role,
            username=username,
            is_admin=is_admin,
        )

    except Exception as e:
        print(f"Error loading subjects: {e}")
        user_role = session.get("role")
        username = session.get("username")
        return render_template(
            "subject_selection.html",
            subjects={},
            user_role=user_role,
            username=username,
        )


@main_bp.route("/subjects/<subject>")
@cache.cached(timeout=60, key_prefix=_subject_page_cache_key)
def subject_page(subject):
    """Display subtopics for a specific subject."""
    try:
        data_service = get_data_service()
        progress_service = get_progress_service()

        # Load subject configuration and info
        subject_config = data_service.load_subject_config(subject)
        subject_info = data_service.load_subject_info(subject)

        if not subject_config or not subject_info:
            print(f"Subject data not found for: {subject}")
            return redirect(url_for("main.subject_selection"))

        subtopics = filter_active_subtopics(subject_config.get("subtopics", {}))

        # Calculate actual counts for each subtopic by checking the files
        for subtopic_id, subtopic_data in subtopics.items():
            try:
                # Count quiz questions
                quiz_data = get_quiz_data(subject, subtopic_id)
                question_count = len(quiz_data) if quiz_data else 0

                # Count lesson plans
                lesson_plans = get_lesson_plans(subject, subtopic_id)
                lesson_count = len(lesson_plans) if lesson_plans else 0

                # Count videos
                video_data = get_video_data(subject, subtopic_id)
                video_count = len(video_data.get("videos", [])) if video_data else 0

                # Update subtopic data with actual counts
                subtopic_data["question_count"] = question_count
                subtopic_data["lesson_count"] = lesson_count
                subtopic_data["video_count"] = video_count

                # Get progress information
                progress_stats = progress_service.check_subtopic_progress(
                    subject, subtopic_id, lesson_count, video_count
                )
                subtopic_data["progress"] = progress_stats

            except Exception as e:
                print(f"Error processing subtopic {subtopic_id}: {e}")
                subtopic_data["question_count"] = 0
                subtopic_data["lesson_count"] = 0
                subtopic_data["video_count"] = 0
                subtopic_data["progress"] = {
                    "overall": {"completion_percentage": 0, "is_complete": False}
                }

        return render_template(
            "python_subject.html",
            subject=subject,
            subject_info=subject_info,
            subtopics=subtopics,
            admin_override=progress_service.get_admin_override_status(),
        )

    except Exception as e:
        print(f"Error loading subject page: {e}")
        return redirect(url_for("main.subject_selection"))


@main_bp.route("/python")
def python_subject_page():
    """Direct route to Python subject - for backward compatibility."""
    return redirect(url_for("main.subject_page", subject="python"))


@main_bp.route("/subjects/<subject>/<subtopic>/prerequisites")
def subtopic_prerequisites(subject, subtopic):
    """Display a friendly message when subtopic prerequisites are missing."""

    try:
        data_service = get_data_service()
        progress_service = get_progress_service()

        subject_config = data_service.load_subject_config(subject)
        if not subject_config:
            return redirect(url_for("main.subject_selection"))

        subtopics = filter_active_subtopics(subject_config.get("subtopics", {}))
        if subtopic not in subtopics:
            return redirect(url_for("main.subject_page", subject=subject))

        prerequisite_status = progress_service.check_subtopic_prerequisites(
            subject, subtopic
        )

        if prerequisite_status.get("can_access_subtopic"):
            return redirect(url_for("main.subject_page", subject=subject))

        subtopic_name = subtopics[subtopic].get("name", subtopic.title())

        return render_template(
            "prerequisites_error.html",
            subject=subject,
            subtopic=subtopic_name,
            subtopic_id=subtopic,
            missing_prerequisites=prerequisite_status.get("missing_prerequisites", []),
            missing_ids=prerequisite_status.get("missing_prerequisite_ids", []),
            prerequisites=prerequisite_status,
        )

    except Exception as exc:
        print(f"Error rendering prerequisites page for {subject}/{subtopic}: {exc}")
        return redirect(url_for("main.subject_page", subject=subject))


# ============================================================================
# QUIZ ROUTES
# ============================================================================


@main_bp.route("/quiz/<subject>/<subtopic>")
def quiz_page(subject, subtopic):
    """Serves the initial quiz for any subject/subtopic."""
    try:
        data_service = get_data_service()
        progress_service = get_progress_service()

        # Validate that the subject/subtopic exists
        if not data_service.validate_subject_subtopic(subject, subtopic):
            return (
                f"Error: Subject '{subject}' with subtopic '{subtopic}' not found.",
                404,
            )

        subject_config = data_service.load_subject_config(subject) or {}
        subtopic_meta = (
            subject_config.get("subtopics", {}) or {}
        ).get(subtopic, {})
        if not is_active_subtopic(subtopic_meta):
            return redirect(url_for("main.subject_page", subject=subject))

        # Clear previous session data for this subject/subtopic
        progress_service.clear_session_data(subject, subtopic)
        progress_service.reset_quiz_context()

        # Load quiz data
        quiz_questions = get_quiz_data(subject, subtopic)
        quiz_title = data_service.get_quiz_title(subject, subtopic)

        if not quiz_questions:
            return f"Error: No quiz questions found for {subject}/{subtopic}.", 404

        # Set session data for quiz
        progress_service.set_quiz_session_data(
            subject, subtopic, "initial", quiz_questions
        )
        progress_service.clear_remedial_quiz_data(subject, subtopic)

        return render_template(
            "quiz.html",
            questions=quiz_questions,
            quiz_title=quiz_title,
            admin_override=progress_service.get_admin_override_status(),
        )

    except Exception as e:
        print(f"Error loading quiz: {e}")
        return f"Error loading quiz: {e}", 500


@main_bp.route("/analyze", methods=["POST"])
def analyze_quiz():
    """Analyze quiz results and provide recommendations."""
    try:
        progress_service = get_progress_service()
        ai_service = get_ai_service()

        payload = request.get_json(silent=True) or {}
        raw_answers = payload.get("answers") or {}
        if not isinstance(raw_answers, dict):
            raw_answers = {}

        current_subject = session.get("current_subject")
        current_subtopic = session.get("current_subtopic")

        if not current_subject or not current_subtopic:
            return "Error: No active quiz session found.", 400

        quiz_session = progress_service.get_quiz_session_data(
            current_subject, current_subtopic
        )
        questions = quiz_session.get("questions", []) or []

        if not questions:
            return "Error: No quiz questions found in session.", 400

        answers: List[str] = []
        for index in range(len(questions)):
            answers.append(str(raw_answers.get(f"q{index}", "")).strip())

        analysis_result = ai_service.analyze_quiz_performance(
            questions, answers, current_subject, current_subtopic
        )

        stored_analysis = progress_service.store_quiz_analysis(
            current_subject, current_subtopic, analysis_result
        )
        weak_topic_candidates = (
            stored_analysis.get("weak_tags")
            or stored_analysis.get("weak_topics")
            or stored_analysis.get("missed_tags")
            or stored_analysis.get("weak_areas")
            or []
        )

        if isinstance(weak_topic_candidates, str):
            weak_topic_candidates = [weak_topic_candidates]

        progress_service.set_weak_topics(
            current_subject, current_subtopic, weak_topic_candidates
        )

        # Store wrong answer indices for remedial quiz generation
        wrong_indices = analysis_result.get("wrong_question_indices", [])
        progress_service.store_wrong_indices(
            current_subject, current_subtopic, wrong_indices
        )

        progress_service.store_quiz_answers(current_subject, current_subtopic, answers)

        return jsonify({"success": True, "analysis": stored_analysis})

    except Exception as e:
        print(f"Error analyzing quiz: {e}")
        return f"Error analyzing quiz: {e}", 500


@main_bp.route("/results")
def show_results_page():
    """Display quiz results page with personalized learning recommendations."""
    try:
        data_service = get_data_service()
        progress_service = get_progress_service()
        ai_service = get_ai_service()

        current_subject = session.get("current_subject")
        current_subtopic = session.get("current_subtopic")

        analysis = None
        answers: List[str] = []
        if current_subject and current_subtopic:
            analysis = progress_service.get_quiz_analysis(
                current_subject, current_subtopic
            )
            answers = progress_service.get_quiz_answers(
                current_subject, current_subtopic
            )

        if analysis is None or not current_subject or not current_subtopic:
            return redirect(url_for("main.subject_selection"))

        answers = answers or []

        # Prepare remedial lesson and video maps based on analysis tags
        lesson_plan_map = {}
        video_map = {}

        topics_from_analysis = (
            analysis.get("weak_tags")
            or analysis.get("weak_topics")
            or analysis.get("weak_areas")
            or []
        )

        # Ensure unique order-preserved topics
        normalized_topics = []
        seen_topics = set()
        for topic in topics_from_analysis:
            if not topic:
                continue
            normalized = topic.strip()
            key = normalized.lower()
            if key in seen_topics:
                continue
            seen_topics.add(key)
            normalized_topics.append(normalized)

        # Gather lessons for the current subject/subtopic
        lesson_list: List[Dict[str, Any]] = data_service.get_lesson_plans(
            current_subject, current_subtopic, include_unlisted=False
        ) or []

        # Sort lessons by order field to ensure predictable, pedagogical ordering
        lesson_list.sort(key=lambda x: (x.get("order", 999), x.get("id", "")))

        # Separate ONLY remedial lessons (results page is exclusively for remediation)
        remedial_lessons = [
            l for l in lesson_list if l.get("type", "").lower() == "remedial"
        ]

        # Warning A: Alert if no remedial content available for this subtopic
        if not remedial_lessons:
            print(
                f"[WARNING] No remedial lessons found for {current_subject}/{current_subtopic}. Results page will be empty."
            )

        deduped_topics: List[str] = []
        seen_lessons: Set[str] = set()

        for topic in normalized_topics:
            match = None
            topic_keys = expand_tag_keys(topic)
            if not topic_keys:
                continue

            # Search ONLY remedial lessons with normalized tag matching
            # Results page is exclusively for remediation after quiz identifies weak topics
            for lesson in remedial_lessons:
                raw_tags = lesson.get("tags", [])
                if isinstance(raw_tags, (list, tuple, set)):
                    tags_iter = raw_tags
                elif isinstance(raw_tags, str):
                    tags_iter = [raw_tags]
                else:
                    tags_iter = []

                lesson_tag_keys: Set[str] = set()
                for tag in tags_iter:
                    lesson_tag_keys.update(expand_tag_keys(tag))

                if topic_keys & lesson_tag_keys:
                    match = lesson
                    break

            # Warning B: Alert if no remedial lesson matches this weak topic
            if not match:
                print(
                    f"[WARNING] No remedial lesson found for weak topic '{topic}' in {current_subject}/{current_subtopic}"
                )
                continue  # Skip this topic entirely - no fallback

            # Process the matched lesson - deduplication logic
            lesson_identifier = match.get("id") or match.get("title")
            if not lesson_identifier:
                tags_identifier = ",".join(
                    sorted(
                        tag.lower()
                        for tag in match.get("tags", [])
                        if isinstance(tag, str)
                    )
                )
                lesson_identifier = tags_identifier or json.dumps(match, sort_keys=True)
            lesson_identifier = str(lesson_identifier).strip()
            lesson_key = (
                f"{current_subject}:{current_subtopic}:{lesson_identifier.lower()}"
            )
            if lesson_key in seen_lessons:
                print(
                    f"[INFO] Lesson '{lesson_identifier}' already shown for another weak topic. Skipping duplicate."
                )
                continue

            seen_lessons.add(lesson_key)
            deduped_topics.append(topic)

            # Include a shallow copy to avoid mutating original data
            lesson_plan_map[topic] = {
                **match,
                "subject": current_subject,
                "subtopic": current_subtopic,
            }

        if deduped_topics:
            normalized_topics = deduped_topics
            analysis["weak_topics"] = deduped_topics
            progress_service.store_quiz_analysis(
                current_subject, current_subtopic, analysis
            )

        # Get video data for mapping
        video_data = get_video_data(current_subject, current_subtopic)
        if video_data and isinstance(video_data, dict):
            video_map = video_data.get("videos", {}) or {}

        # Get video recommendations if AI is available
        video_recommendations = []
        if ai_service.is_available():
            video_data = get_video_data(current_subject, current_subtopic)
            if video_data and "videos" in video_data:
                weak_areas = analysis.get("weak_areas", [])
                video_recommendations = ai_service.recommend_videos(
                    current_subject, current_subtopic, weak_areas, video_data["videos"]
                )

        # Determine if remedial quiz should be offered
        score_percentage = analysis.get("score", {}).get("percentage", 0)
        show_remedial = score_percentage < 70  # Threshold for remedial quiz

        return render_template(
            "results.html",
            analysis=analysis,
            ANALYSIS_RESULTS=analysis,
            answers=answers,
            subject=current_subject,
            subtopic=current_subtopic,
            CURRENT_SUBJECT=current_subject,
            CURRENT_SUBTOPIC=current_subtopic,
            LESSON_PLANS=lesson_plan_map,
            VIDEO_DATA=video_map,
            video_recommendations=video_recommendations,
            show_remedial=show_remedial,
            admin_override=session.get("admin_override", False),
            is_admin=session.get("admin_override", False),
            quiz_generation_error=None,
        )

    except Exception as e:
        print(f"Error displaying results: {e}")
        return redirect(url_for("main.subject_selection"))


@main_bp.route("/generate_remedial_quiz")
def generate_remedial_quiz():
    """Generate a remedial quiz based on previous performance."""
    try:
        data_service = get_data_service()
        progress_service = get_progress_service()
        ai_service = get_ai_service()

        current_subject = session.get("current_subject")
        current_subtopic = session.get("current_subtopic")

        if not current_subject or not current_subtopic:
            return (
                jsonify({"success": False, "error": "Error: No active quiz session."}),
                400,
            )

        # Get the original quiz questions that were taken
        quiz_session = progress_service.get_quiz_session_data(
            current_subject, current_subtopic
        )
        original_questions = quiz_session.get("questions", [])

        if not original_questions:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Error: No quiz session found. Please take the initial quiz first.",
                    }
                ),
                400,
            )

        # Get wrong answer indices from the analysis
        wrong_indices = progress_service.get_wrong_indices(
            current_subject, current_subtopic
        )

        weak_topics_raw = progress_service.get_weak_topics(
            current_subject, current_subtopic
        )
        had_stored_weak_topics = bool(weak_topics_raw)

        if not weak_topics_raw:
            stored_analysis = progress_service.get_quiz_analysis(
                current_subject, current_subtopic
            ) or {}
            weak_topics_raw = (
                stored_analysis.get("weak_topics")
                or stored_analysis.get("weak_tags")
                or stored_analysis.get("weak_areas")
                or []
            )

        if isinstance(weak_topics_raw, str):
            weak_topics_raw = [weak_topics_raw]

        weak_topics: List[str] = []
        seen_topics = set()
        for topic in weak_topics_raw or []:
            if not isinstance(topic, str):
                continue
            cleaned = topic.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen_topics:
                continue
            seen_topics.add(key)
            weak_topics.append(cleaned)

        if weak_topics and not had_stored_weak_topics:
            progress_service.set_weak_topics(
                current_subject, current_subtopic, weak_topics
            )

        if not wrong_indices and not weak_topics:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No incorrect answers found. Remedial quiz not needed - you did great!",
                    }
                ),
                400,
            )

        # Get question pool for remedial questions
        question_pool = (
            data_service.get_question_pool_questions(current_subject, current_subtopic)
            or []
        )

        print(
            f"DEBUG: generate_remedial_quiz - subject: {current_subject}, subtopic: {current_subtopic}"
        )
        print(f"DEBUG: original_questions count: {len(original_questions)}")
        print(f"DEBUG: wrong_indices: {wrong_indices}")
        print(f"DEBUG: question_pool loaded, count: {len(question_pool)}")

        if not question_pool:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No question pool available for remedial quiz.",
                    }
                ),
                404,
            )

        # Use AI to generate targeted remedial quiz based on wrong answers
        remedial_questions = ai_service.generate_remedial_quiz(
            original_questions, wrong_indices, question_pool, weak_topics
        )

        print(
            f"DEBUG: remedial_questions returned, count: {len(remedial_questions) if remedial_questions else 0}"
        )

        if not remedial_questions:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Unable to generate remedial quiz. AI service may be unavailable or no suitable questions found in the pool.",
                    }
                ),
                500,
            )

        # Get weak topics for storage (from previous analysis)
        weak_topics = weak_topics or progress_service.get_weak_topics(
            current_subject, current_subtopic
        )

        # Get AI feedback about the selection
        ai_feedback = ai_service.get_last_selection_feedback()

        stored_count = progress_service.set_remedial_quiz_data(
            current_subject, current_subtopic, remedial_questions, weak_topics
        )

        progress_service.set_quiz_session_data(
            current_subject, current_subtopic, "remedial", remedial_questions
        )

        # Store AI feedback in session for display on quiz page
        if ai_feedback:
            session["remedial_feedback"] = ai_feedback.get("feedback", "")
            session["remedial_reasoning"] = ai_feedback.get("reasoning", "")

        return jsonify(
            {
                "success": True,
                "question_count": stored_count,
                "stored_question_count": stored_count,
                "redirect_url": url_for("main.take_remedial_quiz_page"),
                "ai_feedback": ai_feedback.get("feedback", "") if ai_feedback else None,
            }
        )

    except Exception as e:
        print(f"Error generating remedial quiz: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@main_bp.route("/take_remedial_quiz")
def take_remedial_quiz_page():
    """Page for taking the remedial quiz."""
    try:
        progress_service = get_progress_service()

        current_subject = session.get("current_subject")
        current_subtopic = session.get("current_subtopic")

        if not current_subject or not current_subtopic:
            return redirect(url_for("main.subject_selection"))

        remedial_questions = progress_service.get_remedial_quiz_questions(
            current_subject, current_subtopic
        )

        if not remedial_questions:
            return redirect(url_for("main.show_results_page"))

        quiz_title = (
            f"Remedial Quiz - {current_subject.title()} {current_subtopic.title()}"
        )

        # Get AI feedback from session
        ai_feedback = session.get("remedial_feedback", "")
        ai_reasoning = session.get("remedial_reasoning", "")

        # Clear feedback from session after retrieving
        session.pop("remedial_feedback", None)
        session.pop("remedial_reasoning", None)

        return render_template(
            "quiz.html",
            questions=remedial_questions,
            quiz_title=quiz_title,
            is_remedial=True,
            admin_override=progress_service.get_admin_override_status(),
            ai_feedback=ai_feedback,
            ai_reasoning=ai_reasoning,
        )

    except Exception as e:
        print(f"Error loading remedial quiz: {e}")
        return redirect(url_for("main.subject_selection"))
