"""Progress Service Module

Handles all learning progress tracking, session management, and user state.
Extracts progress logic from the main application routes.
"""

from collections import defaultdict
from datetime import datetime
from flask import session, has_request_context, current_app
from typing import Dict, List, Optional, Any, Tuple


class ProgressService:
    """Service class for handling learning progress and session management."""

    def __init__(self):
        """Initialize the progress service."""
        self._test_completed_lessons = {}
        self._test_watched_videos = {}
        self._test_admin_override = False
        self._server_state_store: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._test_server_state_store: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # ============================================================================
    # SESSION KEY MANAGEMENT
    # ============================================================================

    def generate_session_key(self) -> str:
        """Generate a secure, random session key."""

        import secrets

        return secrets.token_hex(32)

    def _get_state_store(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Return the appropriate in-memory store for the current context."""

        if has_request_context():
            return self._server_state_store
        return self._test_server_state_store

    def _get_server_session_id(self) -> str:
        """Return a stable identifier for server-side state."""

        if not has_request_context():
            return "_test_session"

        server_id = session.get("_server_state_id")
        if not server_id:
            server_id = self.generate_session_key()
            session["_server_state_id"] = server_id
            session.permanent = True
        return server_id

    def _get_user_state(
        self, create: bool = False
    ) -> Optional[Dict[str, Dict[str, Any]]]:
        """Fetch the server-side bucket for the active user session."""

        store = self._get_state_store()
        session_id = self._get_server_session_id()
        state = store.get(session_id)

        if state is None and has_request_context():
            fallback = self._test_server_state_store.pop(session_id, None)
            if fallback is not None:
                store[session_id] = fallback
                state = fallback

        if state is None and create:
            state = store.setdefault(session_id, {})

        return state

    def _set_user_state_value(self, category: str, key: str, value: Any) -> None:
        """Store or delete a value in the server-side state bucket."""

        if value is None:
            state = self._get_user_state(create=False)
            if not state:
                return
            category_store = state.get(category)
            if not category_store:
                return
            category_store.pop(key, None)
            if not category_store:
                state.pop(category, None)
            if not state:
                store = self._get_state_store()
                store.pop(self._get_server_session_id(), None)
            return

        state = self._get_user_state(create=True)
        category_store = state.setdefault(category, {})
        category_store[key] = value

    def _get_user_state_value(
        self, category: str, key: str, default: Any = None
    ) -> Any:
        """Retrieve a stored value for the current user session."""

        state = self._get_user_state()
        if not state:
            return default
        return state.get(category, {}).get(key, default)

    def _clear_user_state_for_subject(self, subject: str, subtopic: str) -> None:
        """Remove all server-side data for a specific subject/subtopic."""

        state = self._get_user_state()
        if not state:
            return

        prefix = f"{subject}_{subtopic}_"
        categories = (
            "quiz_questions",
            "quiz_answers",
            "quiz_analysis",
            "remedial_questions",
            "remedial_topics",
        )

        for category in categories:
            category_store = state.get(category)
            if not category_store:
                continue
            keys_to_remove = [key for key in category_store if key.startswith(prefix)]
            for key in keys_to_remove:
                category_store.pop(key, None)
            if not category_store:
                state.pop(category, None)

        if not state:
            store = self._get_state_store()
            store.pop(self._get_server_session_id(), None)

    def get_session_key(self, subject: str, subtopic: str, key_type: str) -> str:
        """Generate a prefixed session key for a specific subject/subtopic."""
        return f"{subject}_{subtopic}_{key_type}"

    def clear_session_data(self, subject: str, subtopic: str) -> None:
        """Clear all session data for a specific subject/subtopic."""
        session_prefix = f"{subject}_{subtopic}"
        keys_to_remove = [
            key for key in session.keys() if key.startswith(session_prefix)
        ]

        for key in keys_to_remove:
            session.pop(key, None)

        completed_key = self.get_session_key(subject, subtopic, "completed_lessons")
        self._test_completed_lessons.pop(completed_key, None)
        watched_key = self.get_session_key(subject, subtopic, "watched_videos")
        self._test_watched_videos.pop(watched_key, None)
        self._clear_user_state_for_subject(subject, subtopic)

    def reset_quiz_context(self) -> None:
        """Clear cross-subject quiz context stored in the session."""

        global_keys = [
            "quiz_analysis",
            "quiz_answers",
            "quiz_generation_error",
        ]

        for key in global_keys:
            session.pop(key, None)

        current_subject = session.get("current_subject")
        current_subtopic = session.get("current_subtopic")
        if current_subject and current_subtopic:
            self.clear_quiz_session_data(current_subject, current_subtopic)

        # Remove the active quiz pointers – they will be re-populated for the next quiz
        session.pop("current_subject", None)
        session.pop("current_subtopic", None)

    def clear_all_session_data(self) -> None:
        """Clear all session data."""
        if has_request_context():
            session_id = session.get("_server_state_id")
        else:
            session_id = "_test_session"
        session.clear()
        self._test_completed_lessons.clear()
        self._test_watched_videos.clear()
        self._test_admin_override = False
        store = self._get_state_store()
        if session_id in store:
            store.pop(session_id, None)

    # ============================================================================
    # LESSON PROGRESS TRACKING
    # ============================================================================

    def _persist_completion(
        self,
        subject: str,
        subtopic: str,
        item_id: str,
        item_type: str,
        completed: bool = True,
    ) -> None:
        """Persist progress changes to the database when a user is authenticated."""
        if not has_request_context():
            return

        user_id = session.get("user_id")
        if not user_id:
            return

        logger = None
        try:
            logger = current_app.logger
        except Exception:
            logger = None

        try:
            from extensions import db
            from models import LessonProgress
        except Exception as import_exc:  # pragma: no cover - defensive
            if logger:
                logger.debug(
                    "Skipping persistent progress due to import error: %s", import_exc
                )
            return

        try:
            progress = LessonProgress.query.filter_by(
                student_id=user_id,
                subject=subject,
                subtopic=subtopic,
                item_id=item_id,
                item_type=item_type,
            ).first()

            if progress:
                progress.completed = completed
                progress.updated_at = datetime.utcnow()
            else:
                progress = LessonProgress(
                    student_id=user_id,
                    subject=subject,
                    subtopic=subtopic,
                    item_id=item_id,
                    item_type=item_type,
                    completed=completed,
                    updated_at=datetime.utcnow(),
                )
                db.session.add(progress)

            db.session.commit()
        except Exception as exc:  # pragma: no cover - logging path
            db.session.rollback()
            if logger:
                logger.warning(
                    "Failed to persist progress for user %s on %s/%s/%s: %s",
                    user_id,
                    subject,
                    subtopic,
                    item_id,
                    exc,
                )

    def mark_lesson_complete(self, subject: str, subtopic: str, lesson_id: str) -> bool:
        """Mark a specific lesson as completed."""
        if not has_request_context():
            key = self.get_session_key(subject, subtopic, "completed_lessons")
            completed = self._test_completed_lessons.setdefault(key, set())
            completed.add(lesson_id)
            return True

        try:
            completed_key = self.get_session_key(subject, subtopic, "completed_lessons")
            completed_lessons = session.get(completed_key, [])

            if lesson_id not in completed_lessons:
                completed_lessons.append(lesson_id)
                session[completed_key] = completed_lessons
                session.permanent = True

            self._persist_completion(subject, subtopic, lesson_id, "lesson", True)
            return True
        except Exception as e:
            print(f"Error marking lesson complete: {e}")
            return False

    def is_lesson_complete(self, subject: str, subtopic: str, lesson_id: str) -> bool:
        """Check if a specific lesson is completed."""
        if not has_request_context():
            key = self.get_session_key(subject, subtopic, "completed_lessons")
            completed = self._test_completed_lessons.get(key, set())
            return lesson_id in completed

        try:
            completed_key = self.get_session_key(subject, subtopic, "completed_lessons")
            completed_lessons = session.get(completed_key, [])
            return lesson_id in completed_lessons
        except Exception as e:
            print(f"Error checking lesson completion: {e}")
            return False

    def get_completed_lessons(self, subject: str, subtopic: str) -> List[str]:
        """Get list of completed lesson IDs for a subject/subtopic."""
        completed_key = self.get_session_key(subject, subtopic, "completed_lessons")
        if not has_request_context():
            return list(self._test_completed_lessons.get(completed_key, set()))
        completed_lessons = session.get(completed_key)
        if completed_lessons:
            return completed_lessons

        user_id = session.get("user_id")
        if not user_id:
            return []

        logger = None
        try:
            logger = current_app.logger
        except Exception:
            logger = None

        try:
            from models import LessonProgress
        except Exception as import_exc:  # pragma: no cover - defensive
            if logger:
                logger.debug(
                    "Unable to hydrate lesson progress from storage: %s", import_exc
                )
            return []

        try:
            records = (
                LessonProgress.query.filter_by(
                    student_id=user_id,
                    subject=subject,
                    subtopic=subtopic,
                    item_type="lesson",
                    completed=True,
                )
                .with_entities(LessonProgress.item_id)
                .all()
            )
        except Exception as exc:
            if logger:
                logger.debug(
                    "Failed to load persisted lesson progress for %s/%s: %s",
                    subject,
                    subtopic,
                    exc,
                )
            return []

        completed_lessons = [str(row.item_id) for row in records]
        session[completed_key] = completed_lessons
        session.permanent = True
        return completed_lessons

    def get_lesson_progress_stats(
        self, subject: str, subtopic: str, total_lessons: int
    ) -> Dict[str, Any]:
        """Get lesson progress statistics for a subject/subtopic."""
        completed_lessons = self.get_completed_lessons(subject, subtopic)
        completed_count = len(completed_lessons)

        return {
            "completed_count": completed_count,
            "total_count": total_lessons,
            "completion_percentage": (
                (completed_count / total_lessons * 100) if total_lessons > 0 else 0
            ),
            "completed_lessons": completed_lessons,
        }

    def migrate_lesson_id(
        self, subject: str, subtopic: str, old_id: str, new_id: str
    ) -> Dict[str, Any]:
        """Migrate a lesson ID in all student progress records.

        This updates all instances of old_id to new_id in completed lessons
        for the given subject/subtopic.

        Args:
            subject: The subject identifier
            subtopic: The subtopic identifier
            old_id: The old lesson ID to replace
            new_id: The new lesson ID to use

        Returns:
            Dictionary with migration results including number of records updated
        """
        try:
            updated_count = 0
            completed_key = self.get_session_key(subject, subtopic, "completed_lessons")

            if not has_request_context():
                # Test mode - update in-memory storage
                if completed_key in self._test_completed_lessons:
                    completed = self._test_completed_lessons[completed_key]
                    if old_id in completed:
                        completed.discard(old_id)
                        completed.add(new_id)
                        updated_count = 1
            else:
                # Production mode - update session
                completed_lessons = session.get(completed_key, [])
                if old_id in completed_lessons:
                    # Replace old_id with new_id
                    completed_lessons = [
                        new_id if lesson_id == old_id else lesson_id
                        for lesson_id in completed_lessons
                    ]
                    session[completed_key] = completed_lessons
                    session.permanent = True
                    updated_count = 1

            return {
                "success": True,
                "updated_count": updated_count,
                "message": f"Migrated lesson ID from '{old_id}' to '{new_id}'",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Error migrating lesson ID: {e}",
            }

    # ============================================================================
    # VIDEO PROGRESS TRACKING
    # ============================================================================

    def mark_video_complete(self, subject: str, subtopic: str, video_id: str) -> bool:
        """Mark a specific video as watched."""
        if not has_request_context():
            key = self.get_session_key(subject, subtopic, "watched_videos")
            watched = self._test_watched_videos.setdefault(key, set())
            watched.add(video_id)
            return True

        try:
            watched_key = self.get_session_key(subject, subtopic, "watched_videos")
            watched_videos = session.get(watched_key, [])

            if video_id not in watched_videos:
                watched_videos.append(video_id)
                session[watched_key] = watched_videos
                session.permanent = True

            self._persist_completion(subject, subtopic, video_id, "video", True)
            return True
        except Exception as e:
            print(f"Error marking video complete: {e}")
            return False

    def is_video_complete(self, subject: str, subtopic: str, video_id: str) -> bool:
        """Check if a specific video is watched."""
        watched_key = self.get_session_key(subject, subtopic, "watched_videos")
        if not has_request_context():
            watched = self._test_watched_videos.get(watched_key, set())
            return video_id in watched
        watched_videos = session.get(watched_key, [])
        return video_id in watched_videos

    def get_watched_videos(self, subject: str, subtopic: str) -> List[str]:
        """Get list of watched video IDs for a subject/subtopic."""
        watched_key = self.get_session_key(subject, subtopic, "watched_videos")
        if not has_request_context():
            return list(self._test_watched_videos.get(watched_key, set()))
        return session.get(watched_key, [])

    def get_video_progress_stats(
        self, subject: str, subtopic: str, total_videos: int
    ) -> Dict[str, Any]:
        """Get video progress statistics for a subject/subtopic."""
        watched_videos = self.get_watched_videos(subject, subtopic)
        watched_count = len(watched_videos)

        return {
            "watched_count": watched_count,
            "total_count": total_videos,
            "completion_percentage": (
                (watched_count / total_videos * 100) if total_videos > 0 else 0
            ),
            "watched_videos": watched_videos,
        }

    # ============================================================================
    # QUIZ PROGRESS TRACKING
    # ============================================================================

    def set_quiz_session_data(
        self, subject: str, subtopic: str, quiz_type: str, questions: List[Dict]
    ) -> None:
        """Set quiz session data for analysis."""
        sanitized_questions = self._sanitize_questions_for_session(questions)
        session[self.get_session_key(subject, subtopic, "current_quiz_type")] = (
            quiz_type
        )
        questions_key = self.get_session_key(
            subject, subtopic, "questions_served_for_analysis"
        )
        self._set_user_state_value("quiz_questions", questions_key, sanitized_questions)
        session["current_subject"] = subject
        session["current_subtopic"] = subtopic

    def get_quiz_session_data(self, subject: str, subtopic: str) -> Dict[str, Any]:
        """Get current quiz session data."""
        questions_key = self.get_session_key(
            subject, subtopic, "questions_served_for_analysis"
        )
        return {
            "quiz_type": session.get(
                self.get_session_key(subject, subtopic, "current_quiz_type")
            ),
            "questions": self._get_user_state_value(
                "quiz_questions", questions_key, []
            ),
            "current_subject": session.get("current_subject"),
            "current_subtopic": session.get("current_subtopic"),
        }

    def clear_quiz_session_data(self, subject: str, subtopic: str) -> None:
        """Clear quiz-specific session data."""
        quiz_keys = [
            self.get_session_key(subject, subtopic, "current_quiz_type"),
        ]

        for key in quiz_keys:
            session.pop(key, None)

        questions_key = self.get_session_key(
            subject, subtopic, "questions_served_for_analysis"
        )
        answers_key = self.get_session_key(subject, subtopic, "quiz_answers")
        analysis_key = self.get_session_key(subject, subtopic, "analysis_results")
        self._set_user_state_value("quiz_questions", questions_key, None)
        self._set_user_state_value("quiz_answers", answers_key, None)
        self._set_user_state_value("quiz_analysis", analysis_key, None)

    def prepare_analysis_for_session(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Return a sanitized copy of analysis data suitable for cookie storage."""
        if not isinstance(analysis, dict):
            return {}

        keys_to_keep = [
            "score",
            "weak_topics",
            "weak_tags",
            "weak_areas",
            "missed_tags",
            "feedback",
            "ai_analysis",
            "recommendations",
            "allowed_tags",
            "used_ai",
        ]

        sanitized = {key: analysis.get(key) for key in keys_to_keep if key in analysis}

        submission = analysis.get("submission_details")
        if submission:
            # Provide a short summary for debugging while keeping cookie sizes small
            if isinstance(submission, list):
                preview = "\n".join(str(part) for part in submission)[:1000]
            else:
                preview = str(submission)[:1000]
            sanitized["submission_preview"] = preview

        raw_response = analysis.get("raw_ai_response")
        if raw_response:
            sanitized["raw_ai_response_preview"] = str(raw_response)[:1000]

        return sanitized

    def store_quiz_analysis(
        self, subject: str, subtopic: str, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Persist quiz analysis results for later use and return sanitized copy."""
        sanitized = self.prepare_analysis_for_session(analysis)
        key = self.get_session_key(subject, subtopic, "analysis_results")
        self._set_user_state_value("quiz_analysis", key, sanitized)
        return sanitized

    def get_quiz_analysis(
        self, subject: str, subtopic: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve stored quiz analysis if available."""
        key = self.get_session_key(subject, subtopic, "analysis_results")
        stored = self._get_user_state_value("quiz_analysis", key)
        if stored is None:
            return None
        return stored

    def store_quiz_answers(
        self, subject: str, subtopic: str, answers: List[str]
    ) -> List[str]:
        """Persist quiz answers server-side for later reference."""

        sanitized_answers = [str(answer)[:300] for answer in answers or []]
        key = self.get_session_key(subject, subtopic, "quiz_answers")
        self._set_user_state_value("quiz_answers", key, sanitized_answers)
        return sanitized_answers

    def get_quiz_answers(self, subject: str, subtopic: str) -> List[str]:
        """Fetch stored quiz answers."""

        key = self.get_session_key(subject, subtopic, "quiz_answers")
        stored = self._get_user_state_value("quiz_answers", key, [])
        if not stored:
            return []
        return list(stored)

    def store_wrong_indices(
        self, subject: str, subtopic: str, wrong_indices: List[int]
    ) -> List[int]:
        """Persist the indices of questions the learner missed."""

        sanitized: List[int] = []
        for value in wrong_indices or []:
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                continue
            if numeric < 0:
                continue
            sanitized.append(numeric)

        key = self.get_session_key(subject, subtopic, "wrong_indices")
        self._set_user_state_value("quiz_analysis", key, sanitized)
        return sanitized

    def get_wrong_indices(self, subject: str, subtopic: str) -> List[int]:
        """Retrieve stored wrong-question indices."""

        key = self.get_session_key(subject, subtopic, "wrong_indices")
        stored = self._get_user_state_value("quiz_analysis", key, [])
        if not stored:
            return []
        return list(stored)

    def set_weak_topics(self, subject: str, subtopic: str, topics: List[str]) -> None:
        """Store normalized weak topics for remedial guidance."""
        normalized: List[str] = []
        seen = set()
        for topic in topics or []:
            if not isinstance(topic, str):
                continue
            cleaned = topic.strip()
            if not cleaned:
                continue
            key_lower = cleaned.lower()
            if key_lower in seen:
                continue
            seen.add(key_lower)
            normalized.append(cleaned)
        weak_key = self.get_session_key(subject, subtopic, "weak_topics")
        session[weak_key] = normalized
        session.permanent = True

    def get_weak_topics(self, subject: str, subtopic: str) -> List[str]:
        """Return stored weak topics, if any."""
        weak_key = self.get_session_key(subject, subtopic, "weak_topics")
        return session.get(weak_key, [])

    def set_remedial_quiz_data(
        self,
        subject: str,
        subtopic: str,
        questions: List[Dict[str, Any]],
        topics: Optional[List[str]] = None,
    ) -> None:
        """Persist remedial quiz questions and related topics."""
        sanitized_questions = self._sanitize_questions_for_session(
            questions, max_questions=10
        )
        questions_key = self.get_session_key(subject, subtopic, "remedial_questions")
        self._set_user_state_value(
            "remedial_questions", questions_key, sanitized_questions
        )
        if not sanitized_questions:
            print(
                f"[ProgressService] No remedial questions stored for {subject}/{subtopic}",
                flush=True,
            )
        else:
            print(
                f"[ProgressService] Stored {len(sanitized_questions)} remedial questions for {subject}/{subtopic}",
                flush=True,
            )
        stored_count = len(sanitized_questions)
        if topics is not None:
            normalized_topics = [
                str(topic)[:300]
                for topic in topics
                if isinstance(topic, str) and topic.strip()
            ]
            topics_key = self.get_session_key(subject, subtopic, "remedial_topics")
            self._set_user_state_value("remedial_topics", topics_key, normalized_topics)
        return stored_count

    def _sanitize_questions_for_session(
        self,
        questions: Optional[List[Dict[str, Any]]],
        max_questions: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        allowed_keys = {
            "id",
            "question",
            "options",
            "type",
            "answer_index",
            "correct_answer",
            "expected_answer",
            "expected_output",
            "starter_code",
            "sample_solution",
            "placeholder",
            "tags",
        }

        sanitized_questions: List[Dict[str, Any]] = []
        if not questions:
            return sanitized_questions

        for question in questions:
            if not isinstance(question, dict):
                continue

            sanitized: Dict[str, Any] = {}
            for key in allowed_keys:
                if key not in question:
                    continue
                value = question.get(key)
                if value is None:
                    continue

                if key == "options" and isinstance(value, list):
                    sanitized[key] = [str(option)[:300] for option in value[:8]]
                elif isinstance(value, str):
                    sanitized[key] = value[:1000]
                else:
                    sanitized[key] = value

            if "question" not in sanitized:
                continue

            identifier = question.get("id") or question.get("question")
            if identifier is not None:
                sanitized.setdefault("id", identifier)

            sanitized_questions.append(sanitized)

            if max_questions is not None and len(sanitized_questions) >= max_questions:
                break

        return sanitized_questions

    def get_remedial_quiz_questions(
        self, subject: str, subtopic: str
    ) -> List[Dict[str, Any]]:
        """Get stored remedial quiz questions."""
        questions_key = self.get_session_key(subject, subtopic, "remedial_questions")
        stored = self._get_user_state_value("remedial_questions", questions_key, [])
        if not stored:
            return []
        return list(stored)

    def get_remedial_topics(self, subject: str, subtopic: str) -> List[str]:
        """Get topics associated with the remedial quiz."""
        topics_key = self.get_session_key(subject, subtopic, "remedial_topics")
        stored = self._get_user_state_value("remedial_topics", topics_key, [])
        if not stored:
            return []
        return list(stored)

    def clear_remedial_quiz_data(self, subject: str, subtopic: str) -> None:
        """Remove remedial quiz data from the session."""
        for suffix, category in (
            ("remedial_questions", "remedial_questions"),
            ("remedial_topics", "remedial_topics"),
        ):
            session.pop(self.get_session_key(subject, subtopic, suffix), None)
            key = self.get_session_key(subject, subtopic, suffix)
            self._set_user_state_value(category, key, None)

    # ============================================================================
    # OVERALL PROGRESS TRACKING
    # ============================================================================

    def check_subtopic_progress(
        self, subject: str, subtopic: str, total_lessons: int, total_videos: int
    ) -> Dict[str, Any]:
        """Check completion status of all lessons and videos for a subject/subtopic."""
        lesson_stats = self.get_lesson_progress_stats(subject, subtopic, total_lessons)
        video_stats = self.get_video_progress_stats(subject, subtopic, total_videos)

        # Calculate overall completion
        total_items = total_lessons + total_videos
        completed_items = lesson_stats["completed_count"] + video_stats["watched_count"]

        overall_percentage = (
            (completed_items / total_items * 100) if total_items > 0 else 0
        )

        return {
            "lessons": lesson_stats,
            "videos": video_stats,
            "overall": {
                "completed_items": completed_items,
                "total_items": total_items,
                "completion_percentage": overall_percentage,
                "is_complete": overall_percentage >= 100,
            },
        }

    def get_all_progress(self) -> Dict[str, Any]:
        """Get all progress data from the current session."""
        progress_data = {}

        # Extract all progress-related session keys
        for key, value in session.items():
            if "_completed_lessons" in key or "_watched_videos" in key:
                # Parse subject and subtopic from key
                parts = key.split("_")
                if len(parts) >= 3:
                    subject = parts[0]
                    subtopic = parts[1]
                    data_type = "_".join(parts[2:])

                    if subject not in progress_data:
                        progress_data[subject] = {}

                    if subtopic not in progress_data[subject]:
                        progress_data[subject][subtopic] = {}

                    progress_data[subject][subtopic][data_type] = value

        return progress_data

    def update_progress(
        self, subject: str, subtopic: str, item_id: str, item_type: str
    ) -> bool:
        """Universal progress update method."""
        try:
            if item_type == "lesson":
                return self.mark_lesson_complete(subject, subtopic, item_id)
            elif item_type == "video":
                return self.mark_video_complete(subject, subtopic, item_id)
            else:
                return False
        except Exception as e:
            print(f"Error updating progress: {e}")
            return False

    def get_student_progress_summary(self, student_id: int) -> Dict[str, Any]:
        """Return aggregated lesson progress for the specified student."""
        summary: Dict[str, Any] = {
            "completed_lessons": 0,
            "total_lessons": 0,
            "subject_count": 0,
            "subtopic_count": 0,
            "subjects": [],
        }

        if not student_id:
            return summary

        logger = None
        try:
            logger = current_app.logger
        except Exception:
            logger = None

        try:
            from models import LessonProgress
            from services import get_data_service
        except Exception as import_exc:  # pragma: no cover - defensive
            if logger:
                logger.debug(
                    "Progress summary unavailable due to import error: %s", import_exc
                )
            return summary

        data_service = get_data_service()

        try:
            subjects_meta = data_service.discover_subjects()
        except Exception as exc:
            subjects_meta = {}
            if logger:
                logger.warning("Unable to discover subjects for summary: %s", exc)

        lesson_records = (
            LessonProgress.query.filter_by(student_id=student_id, item_type="lesson")
            .order_by(LessonProgress.subject.asc(), LessonProgress.subtopic.asc())
            .all()
        )

        progress_by_subtopic: Dict[Tuple[str, str], Dict[str, bool]] = defaultdict(dict)
        for record in lesson_records:
            key = (record.subject, record.subtopic)
            progress_by_subtopic[key][str(record.item_id)] = bool(record.completed)

        subject_order: List[str] = list(subjects_meta.keys())
        for subject_id, _ in progress_by_subtopic.keys():
            if subject_id not in subject_order:
                subject_order.append(subject_id)

        summary_subjects: List[Dict[str, Any]] = []
        total_lessons = 0
        total_completed = 0
        total_subtopics = 0

        for subject_id in subject_order:
            subject_meta = subjects_meta.get(subject_id, {})
            subject_display = subject_meta.get(
                "name", subject_id.replace("_", " ").title()
            )

            try:
                subject_config = data_service.load_subject_config(subject_id) or {}
            except Exception as exc:
                subject_config = {}
                if logger:
                    logger.debug(
                        "Failed to load config for subject %s: %s", subject_id, exc
                    )

            subtopics_config = {}
            if isinstance(subject_config, dict):
                subtopics_config = subject_config.get("subtopics", {}) or {}

            subtopics_in_config = list(subtopics_config.keys())
            subtopics_in_progress = [
                subtopic
                for (subject, subtopic) in progress_by_subtopic.keys()
                if subject == subject_id
            ]

            seen_subtopics = set()
            subtopic_ids: List[str] = []
            for subtopic in subtopics_in_config + subtopics_in_progress:
                if subtopic and subtopic not in seen_subtopics:
                    seen_subtopics.add(subtopic)
                    subtopic_ids.append(subtopic)

            subject_subtopics: List[Dict[str, Any]] = []
            subject_total_lessons = 0
            subject_completed_lessons = 0

            for subtopic_id in subtopic_ids:
                try:
                    lessons = data_service.get_lesson_plans(
                        subject_id, subtopic_id, include_unlisted=False
                    ) or []
                except Exception as exc:
                    lessons = []
                    if logger:
                        logger.debug(
                            "Failed to load lessons for %s/%s: %s",
                            subject_id,
                            subtopic_id,
                            exc,
                        )

                if not lessons and (subject_id, subtopic_id) in progress_by_subtopic:
                    lessons = [
                        {"id": lesson_id, "title": lesson_id.replace("_", " ").title()}
                        for lesson_id in progress_by_subtopic[(subject_id, subtopic_id)]
                    ]

                lesson_entries: List[Dict[str, Any]] = []
                completed_count = 0

                for lesson in lessons:
                    lesson_id = str(lesson.get("id") or "").strip()
                    if not lesson_id:
                        continue

                    completed = progress_by_subtopic.get(
                        (subject_id, subtopic_id), {}
                    ).get(lesson_id, False)
                    if completed:
                        completed_count += 1

                    lesson_entries.append(
                        {
                            "id": lesson_id,
                            "title": lesson.get("title")
                            or lesson.get("name")
                            or lesson_id.replace("_", " ").title(),
                            "completed": completed,
                        }
                    )

                if not lesson_entries:
                    continue

                subtopic_meta = subtopics_config.get(subtopic_id, {})
                subtopic_display = subtopic_meta.get(
                    "name", subtopic_id.replace("_", " ").title()
                )

                subject_subtopics.append(
                    {
                        "id": subtopic_id,
                        "display_name": subtopic_display,
                        "total_lessons": len(lesson_entries),
                        "completed_lessons": completed_count,
                        "lessons": lesson_entries,
                    }
                )

                subject_total_lessons += len(lesson_entries)
                subject_completed_lessons += completed_count

            if not subject_subtopics:
                continue

            summary_subjects.append(
                {
                    "id": subject_id,
                    "display_name": subject_display,
                    "total_lessons": subject_total_lessons,
                    "completed_lessons": subject_completed_lessons,
                    "subtopics": subject_subtopics,
                }
            )
            total_lessons += subject_total_lessons
            total_completed += subject_completed_lessons
            total_subtopics += len(subject_subtopics)

        summary["subjects"] = summary_subjects
        summary["completed_lessons"] = total_completed
        summary["total_lessons"] = total_lessons
        summary["subject_count"] = len(summary_subjects)
        summary["subtopic_count"] = total_subtopics

        return summary

    # ============================================================================
    # ADMIN OVERRIDE FUNCTIONALITY
    # ============================================================================

    def set_admin_override(self, enabled: bool) -> bool:
        """Explicitly set the admin override status."""
        if not has_request_context():
            self._test_admin_override = bool(enabled)
            return self._test_admin_override

        status = bool(enabled)
        session["admin_override"] = status
        session.permanent = True
        return status

    def toggle_admin_override(self) -> bool:
        """Toggle admin override status for debugging/testing."""
        current_status = self.get_admin_override_status()
        return self.set_admin_override(not current_status)

    def get_admin_override_status(self) -> bool:
        """Get current admin override status."""
        if not has_request_context():
            return bool(self._test_admin_override)
        return session.get("admin_override", False)

    def admin_mark_complete(self, subject: str, subtopic: str) -> bool:
        """Mark a topic as complete for admin override functionality."""
        try:
            from services import get_data_service  # Lazy import to avoid circular deps

            data_service = get_data_service()
            loader = data_service.data_loader

            # Mark all lessons as completed
            lessons_payload = loader.load_lesson_plans(subject, subtopic) or {}
            raw_lessons = lessons_payload.get("lessons", [])
            lesson_ids: List[str] = []

            if isinstance(raw_lessons, dict):
                lesson_ids = list(raw_lessons.keys())
            elif isinstance(raw_lessons, list):
                for index, lesson in enumerate(raw_lessons):
                    lesson_id = lesson.get("id") or f"lesson_{index + 1}"
                    lesson_ids.append(lesson_id)

            if lesson_ids:
                completed_key = self.get_session_key(
                    subject, subtopic, "completed_lessons"
                )
                # Use a unique ordered list to avoid duplicate entries
                session[completed_key] = list(dict.fromkeys(lesson_ids))

            # Mark all videos as watched
            videos_payload = loader.load_videos(subject, subtopic) or {}
            raw_videos = videos_payload.get("videos", [])
            video_ids: List[str] = []

            if isinstance(raw_videos, dict):
                video_ids = list(raw_videos.keys())
            elif isinstance(raw_videos, list):
                for index, video in enumerate(raw_videos):
                    video_id = video.get("id") or f"video_{index + 1}"
                    video_ids.append(video_id)

            if video_ids:
                watched_key = self.get_session_key(subject, subtopic, "watched_videos")
                session[watched_key] = list(dict.fromkeys(video_ids))

            # Flag the subtopic as completed via admin override
            override_key = self.get_session_key(subject, subtopic, "admin_complete")
            session[override_key] = True
            session.permanent = True
            return True
        except Exception as e:
            print(f"Error in admin mark complete: {e}")
            return False

    def is_admin_complete(self, subject: str, subtopic: str) -> bool:
        """Check if topic is marked as complete by admin override."""
        override_key = self.get_session_key(subject, subtopic, "admin_complete")
        return session.get(override_key, False)

    # ============================================================================
    # PREREQUISITE CHECKING
    # ============================================================================

    def _collect_subtopic_content_status(
        self,
        subject: str,
        subtopic: str,
        lesson_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gather lesson/video completion state for a subtopic.

        Args:
            subject: The subject slug.
            subtopic: The subtopic slug.
            lesson_type: Optional lesson type filter ("initial", "remedial",
                or None for all lessons). When provided the returned lesson
                statistics will only include lessons matching the requested
                type ("all" lessons are always included).

        Returns:
            A dictionary describing lesson/video completion state constrained
            to the requested lesson type (if any).
        """

        from services import get_data_service  # Lazy import to avoid circular deps

        data_service = get_data_service()
        lessons = data_service.get_lesson_plans(
            subject, subtopic, include_unlisted=False
        ) or []

        lesson_items: List[Tuple[str, Dict[str, Any]]] = []
        normalized_lesson_type = (lesson_type or "").strip().lower()

        def include_lesson(entry: Dict[str, Any]) -> bool:
            if not normalized_lesson_type:
                return True

            raw_value = entry.get("type")
            raw_type = "" if raw_value is None else str(raw_value).strip().lower()

            if normalized_lesson_type == "initial":
                # Treat unspecified or "all" lessons as initial friendly
                return raw_type in {"", "initial", "all"}
            if normalized_lesson_type == "remedial":
                return raw_type in {"remedial", "all"}

            return raw_type == normalized_lesson_type

        for index, lesson in enumerate(lessons):
            lesson = lesson or {}
            if not include_lesson(lesson):
                continue
            lesson_id = lesson.get("id") or f"lesson_{index + 1}"
            lesson_items.append((lesson_id, lesson))

        lesson_titles = {
            lesson_id: lesson.get("title", lesson_id)
            for lesson_id, lesson in lesson_items
        }
        lesson_ids = list(lesson_titles.keys())

        completed_lessons = set(self.get_completed_lessons(subject, subtopic))
        missing_lessons = [
            lesson_titles[lesson_id]
            for lesson_id in lesson_ids
            if lesson_id not in completed_lessons
        ]

        raw_videos: List[Any] = []
        if data_service.videos_file_exists(subject, subtopic):
            videos_data = data_service.get_video_data(subject, subtopic) or {}
            raw_videos = videos_data.get("videos", []) or []

        video_titles: Dict[str, str] = {}
        video_ids: List[str] = []
        for index, video in enumerate(raw_videos):
            if isinstance(video, dict):
                video_id = video.get("id") or f"video_{index + 1}"
                video_title = video.get("title", video_id)
            else:
                video_id = f"video_{index + 1}"
                video_title = video_id
            video_ids.append(video_id)
            video_titles[video_id] = video_title

        watched_videos = set(self.get_watched_videos(subject, subtopic))
        missing_videos = [
            video_titles.get(video_id, video_id)
            for video_id in video_ids
            if video_id not in watched_videos
        ]

        lessons_complete = len(missing_lessons) == 0 if lesson_ids else True
        videos_complete = len(missing_videos) == 0 if video_ids else True
        all_content_complete = lessons_complete and videos_complete

        missing_items: List[str] = []
        missing_items.extend([f"Complete lesson: {title}" for title in missing_lessons])
        missing_items.extend([f"Watch video: {title}" for title in missing_videos])

        return {
            "lesson_ids": lesson_ids,
            "video_ids": video_ids,
            "missing_lessons": missing_lessons,
            "missing_videos": missing_videos,
            "lessons_complete": lessons_complete,
            "videos_complete": videos_complete,
            "missing_items": missing_items,
            "lessons_completed": len(lesson_ids) - len(missing_lessons),
            "videos_watched": len(video_ids) - len(missing_videos),
            "total_lessons": len(lesson_ids),
            "total_videos": len(video_ids),
            "all_content_complete": all_content_complete,
        }

    def check_quiz_prerequisites(self, subject: str, subtopic: str) -> Dict[str, Any]:
        """Evaluate whether the learner can take the quiz for a subject/subtopic."""

        status = self._collect_subtopic_content_status(
            subject, subtopic, lesson_type="initial"
        )

        admin_override = self.get_admin_override_status()
        all_met = admin_override or status["all_content_complete"]

        return {
            "subject": subject,
            "subtopic": subtopic,
            "has_prerequisites": bool(
                status["total_lessons"] or status["total_videos"]
            ),
            "lessons_complete": status["lessons_complete"],
            "lesson_total": status["total_lessons"],
            "lessons_completed": status["lessons_completed"],
            "videos_complete": status["videos_complete"],
            "videos_total": status["total_videos"],
            "videos_watched": status["videos_watched"],
            "missing_items": status["missing_items"],
            "missing_lessons": status["missing_lessons"],
            "missing_videos": status["missing_videos"],
            "admin_override": admin_override,
            "all_met": all_met,
            "can_take_quiz": all_met,
            "prerequisites_met": all_met,
        }

    def check_subtopic_prerequisites(
        self, subject: str, subtopic: str
    ) -> Dict[str, Any]:
        """Determine if prerequisite subtopics are complete for the target subtopic."""

        from services import get_data_service  # Lazy import to avoid circular deps

        data_service = get_data_service()
        subject_config = data_service.load_subject_config(subject) or {}
        subtopics_config = subject_config.get("subtopics", {})
        target_config = subtopics_config.get(subtopic, {})

        # Check if subtopic is inactive (takes priority over prerequisites)
        subtopic_status = target_config.get("status", "active")
        if subtopic_status == "inactive":
            return {
                "subject": subject,
                "subtopic": subtopic,
                "is_active": False,
                "subtopic_inactive": True,
                "can_access_subtopic": False,
                "has_prerequisites": False,
                "admin_override": False,
                "prerequisite_ids": [],
                "prerequisite_details": [],
                "missing_prerequisite_ids": [],
                "missing_prerequisites": [],
                "completed_prerequisites": 0,
                "total_prerequisites": 0,
                "prerequisites_met": False,
                "redirect_url": f"/subjects/{subject}",
            }

        configured_prereqs = target_config.get("prerequisites", []) or []
        prerequisite_ids = [
            prereq
            for prereq in configured_prereqs
            if isinstance(prereq, str) and prereq.strip()
        ]

        admin_override = self.get_admin_override_status()

        prerequisite_details: List[Dict[str, Any]] = []
        missing_ids: List[str] = []
        missing_names: List[str] = []

        for prereq_id in prerequisite_ids:
            prereq_config = subtopics_config.get(prereq_id, {})
            display_name = prereq_config.get(
                "name", prereq_id.replace("_", " ").title()
            )

            if prereq_id not in subtopics_config:
                prerequisite_details.append(
                    {
                        "id": prereq_id,
                        "name": display_name,
                        "is_complete": False,
                        "reason": "not_found",
                        "lesson_total": 0,
                        "lessons_completed": 0,
                        "video_total": 0,
                        "videos_watched": 0,
                    }
                )
                missing_ids.append(prereq_id)
                missing_names.append(display_name)
                continue

            progress = self._collect_subtopic_content_status(
                subject, prereq_id, lesson_type="initial"
            )
            is_complete = progress["all_content_complete"]

            prerequisite_details.append(
                {
                    "id": prereq_id,
                    "name": display_name,
                    "is_complete": is_complete,
                    "lesson_total": progress["total_lessons"],
                    "lessons_completed": progress["lessons_completed"],
                    "video_total": progress["total_videos"],
                    "videos_watched": progress["videos_watched"],
                }
            )

            if not is_complete:
                missing_ids.append(prereq_id)
                missing_names.append(display_name)

        prerequisites_met = admin_override or not missing_ids

        return {
            "subject": subject,
            "subtopic": subtopic,
            "is_active": True,
            "subtopic_inactive": False,
            "has_prerequisites": bool(prerequisite_ids),
            "admin_override": admin_override,
            "prerequisite_ids": prerequisite_ids,
            "prerequisite_details": prerequisite_details,
            "missing_prerequisite_ids": missing_ids,
            "missing_prerequisites": missing_names,
            "completed_prerequisites": len(prerequisite_ids) - len(missing_ids),
            "total_prerequisites": len(prerequisite_ids),
            "can_access_subtopic": prerequisites_met,
            "prerequisites_met": prerequisites_met,
            "redirect_url": f"/subjects/{subject}/{subtopic}/prerequisites",
        }
