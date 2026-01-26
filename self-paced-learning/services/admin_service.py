"""Admin Service Module

Handles all administrative operations including subject management,
lesson administration, and system oversight. Extracts admin logic
from the main application routes.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from .data_service import DataService
from .progress_service import ProgressService


class AdminService:
    """Service class for handling administrative operations."""

    def __init__(
        self,
        data_service: Optional[DataService] = None,
        progress_service: Optional[ProgressService] = None,
    ):
        """Initialize the admin service with required dependencies.

        Args:
            data_service: Optional pre-configured :class:`DataService` instance.
                When omitted a new instance targeting the default data root is
                created, which keeps legacy tests working without manual
                wiring.
            progress_service: Optional :class:`ProgressService` instance. A new
                instance is created when not provided.
        """

        self.data_service = data_service or DataService()
        self.progress_service = progress_service or ProgressService()

    # ============================================================================
    # DASHBOARD AND OVERVIEW
    # ============================================================================

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Generate comprehensive dashboard statistics."""
        try:
            subjects = self.data_service.discover_subjects()
            stats = {
                "total_subjects": len(subjects),
                "total_subtopics": 0,
                "total_lessons": 0,
                "total_questions": 0,
                "subjects_without_content": 0,
            }

            subjects_data = {}

            for subject_id, subject_info in subjects.items():
                subject_config = self.data_service.load_subject_config(subject_id)

                if subject_config and "subtopics" in subject_config:
                    subtopics = subject_config["subtopics"]
                    stats["total_subtopics"] += len(subtopics)

                    subject_lessons = 0
                    subject_questions = 0

                    for subtopic_id in subtopics.keys():
                        # Count lessons
                        lessons = self.data_service.get_lesson_plans(
                            subject_id, subtopic_id
                        )
                        lesson_count = len(lessons) if lessons else 0
                        subject_lessons += lesson_count

                        # Count questions
                        quiz_data = self.data_service.get_quiz_data(
                            subject_id, subtopic_id
                        )
                        question_count = (
                            len(quiz_data.get("questions", [])) if quiz_data else 0
                        )
                        subject_questions += question_count

                    stats["total_lessons"] += subject_lessons
                    stats["total_questions"] += subject_questions

                    if subject_lessons == 0 and subject_questions == 0:
                        stats["subjects_without_content"] += 1

                    subjects_data[subject_id] = {
                        "name": subject_info.get("name", subject_id.title()),
                        "description": subject_info.get("description", ""),
                        "lessons": subject_lessons,
                        "questions": subject_questions,
                        "subtopics": len(subtopics),
                    }
                else:
                    stats["subjects_without_content"] += 1
                    subjects_data[subject_id] = {
                        "name": subject_info.get("name", subject_id.title()),
                        "description": subject_info.get("description", ""),
                        "lessons": 0,
                        "questions": 0,
                        "subtopics": 0,
                    }

            return {"stats": stats, "subjects": subjects_data}

        except Exception as e:
            print(f"Error generating dashboard stats: {e}")
            return {
                "stats": {
                    "total_subjects": 0,
                    "total_subtopics": 0,
                    "total_lessons": 0,
                    "total_questions": 0,
                    "subjects_without_content": 0,
                },
                "subjects": {},
            }

    # ============================================================================
    # SUBJECT MANAGEMENT
    # ============================================================================

    def create_subject(self, subject_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new subject with validation."""
        try:
            subject_id = subject_data.get("id", "").lower().replace(" ", "_")
            subject_name = subject_data.get("name", "")
            description = subject_data.get("description", "")
            icon = subject_data.get("icon", "fas fa-book")
            color = subject_data.get("color", "#007bff")

            # Validation
            if not subject_id or not subject_name:
                return {"success": False, "error": "Subject ID and name are required"}

            # Check if subject already exists
            subjects = self.data_service.discover_subjects()
            if subject_id in subjects:
                return {"success": False, "error": "Subject already exists"}

            # Prepare subject data structure
            complete_subject_data = {
                "info": {
                    "name": subject_name,
                    "description": description,
                    "icon": icon,
                    "color": color,
                    "created_date": "2025-10-02",
                },
                "config": {"subtopics": {}, "updated_date": "2025-10-02"},
            }

            # Create the subject
            success = self.data_service.create_subject(
                subject_id, complete_subject_data
            )

            if success:
                return {
                    "success": True,
                    "message": "Subject created successfully",
                    "subject_id": subject_id,
                }
            else:
                return {"success": False, "error": "Failed to create subject"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_subject(self, subject_id: str) -> Dict[str, Any]:
        """Delete a subject with validation."""
        try:
            # Validate subject exists
            subjects = self.data_service.discover_subjects()
            if subject_id not in subjects:
                return {"success": False, "error": "Subject not found"}

            # Delete the subject
            success = self.data_service.delete_subject(subject_id)

            if success:
                return {"success": True, "message": "Subject deleted successfully"}
            else:
                return {"success": False, "error": "Failed to delete subject"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_subtopic(self, subject: str, subtopic_id: str) -> Dict[str, Any]:
        """Delete a subtopic with validation."""
        try:
            # Validate subject exists
            subjects = self.data_service.discover_subjects()
            if subject not in subjects:
                return {"success": False, "error": "Subject not found"}

            # Validate subtopic exists
            subject_config = self.data_service.load_subject_config(subject)
            if not subject_config:
                return {"success": False, "error": "Subject configuration not found"}

            subtopics = subject_config.get("subtopics", {})
            if subtopic_id not in subtopics:
                return {"success": False, "error": "Subtopic not found"}

            # Delete the subtopic
            success = self.data_service.delete_subtopic(subject, subtopic_id)

            if success:
                return {"success": True, "message": "Subtopic deleted successfully"}
            else:
                return {"success": False, "error": "Failed to delete subtopic"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_subject(
        self, subject_id: str, update_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update subject information and configuration data."""

        if not subject_id:
            return {"success": False, "error": "Subject identifier is required"}

        normalised_subject = subject_id.strip().lower().replace(" ", "_")
        if not normalised_subject:
            return {"success": False, "error": "Subject identifier is invalid"}

        try:
            subjects = self.data_service.discover_subjects()
            if normalised_subject not in subjects:
                return {"success": False, "error": "Subject not found", "status": 404}

            subject_info = update_payload.get("subject_info")
            subtopics = update_payload.get("subtopics")
            allowed_tags = update_payload.get("allowed_tags")
            rename_subtopic = update_payload.get("rename_subtopic")

            if subject_info is None and subtopics is None and allowed_tags is None:
                return {
                    "success": False,
                    "error": "No updatable fields provided",
                    "status": 400,
                }

            updated = self.data_service.update_subject(
                normalised_subject,
                subject_info=subject_info,
                subtopics=subtopics,
                allowed_tags=allowed_tags,
                rename_subtopic=rename_subtopic,
            )

            if not updated:
                return {
                    "success": False,
                    "error": "Subject update did not modify any data",
                    "status": 400,
                }

            return {
                "success": True,
                "message": "Subject updated successfully",
                "subject_id": normalised_subject,
            }

        except (TypeError, ValueError) as validation_error:
            return {
                "success": False,
                "error": str(validation_error),
                "status": 400,
            }
        except FileNotFoundError as missing_error:
            return {
                "success": False,
                "error": str(missing_error),
                "status": 404,
            }
        except Exception as exc:  # pragma: no cover - defensive logging path
            return {"success": False, "error": str(exc), "status": 500}

    # ============================================================================
    # LESSON MANAGEMENT
    # ============================================================================

    def _build_subject_subtopic_overview(
        self,
        subject_filter: Optional[str] = None,
        subtopic_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Collect subtopic information for each subject with aggregated stats."""

        subjects = self.data_service.discover_subjects()

        overview: Dict[str, Any] = {}
        stats = {
            "total_subjects": 0,
            "total_subtopics": 0,
            "total_lessons": 0,
            "total_initial_questions": 0,
            "total_pool_questions": 0,
            "subtopics_without_lessons": 0,
            "subtopics_without_questions": 0,
        }

        for subject_id, subject_info in subjects.items():
            if subject_filter and subject_id != subject_filter:
                continue

            subject_config = self.data_service.load_subject_config(subject_id)
            if not subject_config or "subtopics" not in subject_config:
                continue

            subtopics_data = []

            for subtopic_id, subtopic_cfg in subject_config["subtopics"].items():
                if subtopic_filter and subtopic_id != subtopic_filter:
                    continue

                lessons = self.data_service.get_lesson_plans(subject_id, subtopic_id)
                quiz_data = self.data_service.get_quiz_data(subject_id, subtopic_id)
                pool_data = self.data_service.get_question_pool_questions(
                    subject_id, subtopic_id
                )

                lesson_count = len(lessons) if lessons else 0
                initial_count = len(quiz_data.get("questions", [])) if quiz_data else 0
                pool_count = len(pool_data) if pool_data else 0

                subtopics_data.append(
                    {
                        "id": subtopic_id,
                        "name": subtopic_cfg.get("name", subtopic_id.title()),
                        "description": subtopic_cfg.get("description", ""),
                        "order": subtopic_cfg.get("order", 0),
                        "status": subtopic_cfg.get("status", "active"),
                        "estimated_time": subtopic_cfg.get("estimated_time", ""),
                        "video_count": subtopic_cfg.get("video_count", 0),
                        "prerequisites": subtopic_cfg.get("prerequisites", []),
                        "lesson_count": lesson_count,
                        "quiz_questions_count": initial_count,
                        "pool_questions_count": pool_count,
                    }
                )

                stats["total_subtopics"] += 1
                stats["total_lessons"] += lesson_count
                stats["total_initial_questions"] += initial_count
                stats["total_pool_questions"] += pool_count

                if lesson_count == 0:
                    stats["subtopics_without_lessons"] += 1
                if initial_count == 0 and pool_count == 0:
                    stats["subtopics_without_questions"] += 1

            if subtopics_data:
                subtopics_data.sort(key=lambda item: item.get("order", 0))
                overview[subject_id] = {
                    "id": subject_id,
                    "name": subject_info.get("name", subject_id.title()),
                    "description": subject_info.get("description", ""),
                    "icon": subject_info.get("icon", "fas fa-book"),
                    "color": subject_info.get("color", "#4a5568"),
                    "subtopics": subtopics_data,
                }

        stats["total_subjects"] = len(overview)

        return {"subjects": overview, "stats": stats}

    def get_lessons_overview(
        self,
        subject_filter: Optional[str] = None,
        subtopic_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get comprehensive lessons overview with optional filtering."""
        try:
            if subject_filter and subtopic_filter:
                subjects = self.data_service.discover_subjects()

                # Filtered view for specific subject/subtopic
                if not self.data_service.validate_subject_subtopic(
                    subject_filter, subtopic_filter
                ):
                    return {
                        "success": False,
                        "error": f"Subject '{subject_filter}' with subtopic '{subtopic_filter}' not found",
                    }

                lessons = self.data_service.get_lesson_plans(
                    subject_filter, subtopic_filter
                )

                if lessons:
                    subject_name = subjects.get(subject_filter, {}).get(
                        "name", subject_filter.title()
                    )
                    subject_config = self.data_service.load_subject_config(
                        subject_filter
                    )
                    subtopic_name = subtopic_filter.title()
                    if (
                        subject_config
                        and "subtopics" in subject_config
                        and subtopic_filter in subject_config["subtopics"]
                    ):
                        subtopic_name = subject_config["subtopics"][
                            subtopic_filter
                        ].get("name", subtopic_filter.title())

                    for lesson in lessons:
                        lesson["subject"] = subject_filter
                        lesson["subtopic"] = subtopic_filter
                        lesson["subject_name"] = subject_name
                        lesson["subtopic_name"] = subtopic_name

                return {
                    "success": True,
                    "lessons": lessons or [],
                    "filtered_view": True,
                    "subject_filter": subject_filter,
                    "subtopic_filter": subtopic_filter,
                }

            overview = self._build_subject_subtopic_overview(
                subject_filter, subtopic_filter
            )

            subjects_overview = overview.get("subjects", {})

            subjects_with_lessons = 0
            subtopics_with_lessons = 0
            total_lessons = 0

            for subject_id, subject_data in subjects_overview.items():
                subject_lesson_total = 0

                for subtopic in subject_data.get("subtopics", []):
                    lessons = self.data_service.get_lesson_plans(
                        subject_id, subtopic.get("id")
                    )

                    normalized_lessons = []
                    for lesson in lessons or []:
                        normalized_lessons.append(
                            {
                                "id": lesson.get("id"),
                                "title": lesson.get("title", "Untitled Lesson"),
                                "type": lesson.get("type", "lesson"),
                                "order": lesson.get("order", 0),
                                "tags": lesson.get("tags", []),
                                "content_length": len(lesson.get("content", []) or []),
                                "updated_date": lesson.get("updated_date", ""),
                            }
                        )

                    normalized_lessons.sort(
                        key=lambda item: (
                            item.get("order", 0),
                            (item.get("title") or "").lower(),
                        )
                    )

                    subtopic["lessons"] = normalized_lessons
                    subtopic["lesson_count"] = len(normalized_lessons)

                    if normalized_lessons:
                        subtopics_with_lessons += 1

                    subject_lesson_total += len(normalized_lessons)
                    total_lessons += len(normalized_lessons)

                subject_data["lesson_count"] = subject_lesson_total

                if subject_lesson_total > 0:
                    subjects_with_lessons += 1

            stats = overview.get("stats", {})
            stats["total_lessons"] = total_lessons
            stats["subjects_with_lessons"] = subjects_with_lessons
            stats["subtopics_with_lessons"] = subtopics_with_lessons

            return {
                "success": True,
                "subjects": subjects_overview,
                "stats": stats,
                "subject_filter": subject_filter,
                "subtopic_filter": subtopic_filter,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_lesson(self, lesson_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new lesson with validation."""
        try:
            subject = lesson_data.get("subject")
            subtopic = lesson_data.get("subtopic")

            # Validation
            if not subject or not subtopic:
                return {"success": False, "error": "Subject and subtopic are required"}

            if not self.data_service.validate_subject_subtopic(subject, subtopic):
                return {
                    "success": False,
                    "error": "Invalid subject/subtopic combination",
                }

            # Generate lesson ID if not provided
            lesson_id = lesson_data.get("id")
            if not lesson_id:
                # Generate ID from title
                title = lesson_data.get("title", "")
                lesson_id = title.lower().replace(" ", "_").replace("-", "_")
                lesson_data["id"] = lesson_id

            # Handle lesson type - check both 'type' and 'lessonType' fields
            lesson_type = lesson_data.get("type") or lesson_data.get("lessonType")
            if lesson_type:
                lesson_data["type"] = lesson_type.strip().lower()
            else:
                lesson_data["type"] = "remedial"  # Default to remedial

            # Set default values
            lesson_data.setdefault("tags", [])
            lesson_data.setdefault("updated_date", "2025-10-02")

            # Auto-assign order if not provided
            if (
                "order" not in lesson_data
                or lesson_data.get("order") is None
                or lesson_data.get("order") == ""
            ):
                existing_lessons = self.data_service.get_lesson_plans(subject, subtopic) or []
                max_order = 0
                for lesson in existing_lessons:
                    if not isinstance(lesson, dict):
                        continue
                    lesson_order = lesson.get("order")
                    if lesson_order is None or lesson_order == "":
                        continue
                    try:
                        max_order = max(max_order, int(lesson_order))
                    except Exception:
                        continue
                lesson_data["order"] = max_order + 1 if max_order else 1

            # Save the lesson
            success = self.data_service.save_lesson_to_file(
                subject, subtopic, lesson_id, lesson_data
            )

            if success:
                return {
                    "success": True,
                    "message": "Lesson created successfully",
                    "lesson_id": lesson_id,
                }
            else:
                return {"success": False, "error": "Failed to save lesson"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_lesson(
        self,
        subject: str,
        subtopic: str,
        lesson_id: str,
        lesson_data: Dict[str, Any],
        order_provided: bool = False,
    ) -> Dict[str, Any]:
        """Update an existing lesson.

        If the lesson ID is changed, this will automatically migrate all student
        progress records from the old ID to the new ID.
        """
        try:
            # Validation
            if not self.data_service.validate_subject_subtopic(subject, subtopic):
                return {
                    "success": False,
                    "error": "Invalid subject/subtopic combination",
                }

            # Capture current lesson ordering so we can preserve drag order after updates
            current_lessons = self.data_service.get_lesson_plans(subject, subtopic) or []
            lesson_order: List[str] = [
                lesson.get("id")
                for lesson in current_lessons
                if isinstance(lesson, dict) and lesson.get("id")
            ]
            existing_order = None
            for lesson in current_lessons:
                if isinstance(lesson, dict) and lesson.get("id") == lesson_id:
                    existing_order = lesson.get("order")
                    break

            # Check if lesson ID is being changed
            new_lesson_id = lesson_data.get("id", lesson_id)
            id_changed = new_lesson_id != lesson_id

            if id_changed:
                # Validate that the new ID doesn't already exist
                existing_lessons = self.data_service.get_lesson_map(subject, subtopic)
                if new_lesson_id in existing_lessons:
                    return {
                        "success": False,
                        "error": f"Lesson ID '{new_lesson_id}' already exists. Please choose a different ID.",
                    }

                # Delete the old lesson entry
                delete_success = self.data_service.delete_lesson_from_file(
                    subject, subtopic, lesson_id
                )
                if not delete_success:
                    return {
                        "success": False,
                        "error": "Failed to remove old lesson entry during ID change",
                    }

                # Migrate student progress from old ID to new ID
                progress_service = self.progress_service
                migration_result = progress_service.migrate_lesson_id(
                    subject, subtopic, lesson_id, new_lesson_id
                )

                if not migration_result.get("success"):
                    return {
                        "success": False,
                        "error": f"Failed to migrate student progress: {migration_result.get('error')}",
                    }
                # Keep the lesson in its original position
                if lesson_id in lesson_order:
                    idx = lesson_order.index(lesson_id)
                    lesson_order[idx] = new_lesson_id
                else:
                    lesson_order.append(new_lesson_id)
            else:
                if new_lesson_id not in lesson_order:
                    lesson_order.append(new_lesson_id)

            # Respect explicit order value from the payload if provided and changed
            explicit_order = lesson_data.get("order")
            explicit_order_int = None
            if explicit_order is not None:
                try:
                    explicit_order_int = int(explicit_order)
                except Exception:
                    explicit_order_int = None

            existing_order_int = None
            if existing_order is not None:
                try:
                    existing_order_int = int(existing_order)
                except Exception:
                    existing_order_int = None

            order_changed = (
                order_provided
                and explicit_order_int is not None
                and (existing_order_int is None or explicit_order_int != existing_order_int)
            )

            if order_changed and lesson_order and explicit_order_int is not None:
                desired_index = max(explicit_order_int - 1, 0)
                # Remove any existing occurrence before reinserting
                lesson_order = [lid for lid in lesson_order if lid != new_lesson_id]
                desired_index = min(desired_index, len(lesson_order))
                lesson_order.insert(desired_index, new_lesson_id)

            # Ensure the new lesson ID is set
            lesson_data["id"] = new_lesson_id
            lesson_data["updated_date"] = "2025-10-02"

            # Save the lesson with the new ID
            success = self.data_service.save_lesson_to_file(
                subject, subtopic, new_lesson_id, lesson_data
            )

            if success:
                message = "Lesson updated successfully"
                if id_changed:
                    message += f" (ID changed from '{lesson_id}' to '{new_lesson_id}')"

                # Reapply ordering only when explicitly changed
                if order_changed and lesson_order:
                    self.reorder_lessons(subject, subtopic, lesson_order)

                return {
                    "success": True,
                    "message": message,
                    "id_changed": id_changed,
                    "new_lesson_id": new_lesson_id,
                }
            else:
                return {"success": False, "error": "Failed to update lesson"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_lesson(
        self, subject: str, subtopic: str, lesson_id: str
    ) -> Dict[str, Any]:
        """Delete a lesson with validation."""
        try:
            # Validation
            if not self.data_service.validate_subject_subtopic(subject, subtopic):
                return {
                    "success": False,
                    "error": "Invalid subject/subtopic combination",
                }

            # Delete the lesson
            success = self.data_service.delete_lesson_from_file(
                subject, subtopic, lesson_id
            )

            if success:
                return {"success": True, "message": "Lesson deleted successfully"}
            else:
                return {
                    "success": False,
                    "error": "Lesson not found or failed to delete",
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def reorder_lessons(
        self, subject: str, subtopic: str, lesson_order: List[str]
    ) -> Dict[str, Any]:
        """Reorder lessons for a specific subject/subtopic."""
        try:
            # Get current lessons
            lessons = self.data_service.get_lesson_plans(subject, subtopic)

            if not lessons:
                return {
                    "success": False,
                    "error": "No lessons found for this subject/subtopic",
                }

            # Create a mapping of lesson ID to lesson data
            lesson_map = {lesson.get("id"): lesson for lesson in lessons}

            # Reorder lessons according to the provided order and update their
            # numeric order attribute so the student experience reflects the new
            # arrangement.
            reordered_lessons: List[Dict[str, Any]] = []
            seen_lessons = set()

            for position, lesson_id in enumerate(lesson_order, start=1):
                if lesson_id in lesson_map:
                    lesson_copy = dict(lesson_map[lesson_id])
                    lesson_copy["order"] = position
                    reordered_lessons.append(lesson_copy)
                    seen_lessons.add(lesson_id)

            # Add any lessons not in the order list to the end while
            # continuing the sequential numbering.
            next_position = len(reordered_lessons) + 1
            for lesson in lessons:
                lesson_id = lesson.get("id")
                if lesson_id in seen_lessons:
                    continue

                lesson_copy = dict(lesson)
                lesson_copy["order"] = next_position
                reordered_lessons.append(lesson_copy)
                next_position += 1

            # Save the reordered lessons
            lesson_file_path = os.path.join(
                self.data_service.data_root_path,
                "subjects",
                subject,
                subtopic,
                "lesson_plans.json",
            )

            lesson_plans_data = {
                "lessons": reordered_lessons,
                "updated_date": "2025-10-02",
            }

            os.makedirs(os.path.dirname(lesson_file_path), exist_ok=True)

            with open(lesson_file_path, "w", encoding="utf-8") as f:
                json.dump(lesson_plans_data, f, indent=2, ensure_ascii=False)

            # Ensure subsequent reads observe the updated ordering
            self.data_service.clear_cache_for_subject_subtopic(subject, subtopic)

            return {"success": True, "message": "Lessons reordered successfully"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================================
    # QUESTIONS MANAGEMENT
    # ============================================================================

    def get_questions_overview(
        self,
        subject_filter: Optional[str] = None,
        subtopic_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get comprehensive questions overview with optional filtering."""
        try:
            overview = self._build_subject_subtopic_overview(
                subject_filter, subtopic_filter
            )

            stats = overview["stats"]

            return {
                "success": True,
                "subjects": overview["subjects"],
                "stats": stats,
                "subject_filter": subject_filter,
                "subtopic_filter": subtopic_filter,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_subtopics_overview(
        self,
        subject_filter: Optional[str] = None,
        subtopic_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get overview of all subtopics with lesson and question coverage."""

        try:
            overview = self._build_subject_subtopic_overview(
                subject_filter, subtopic_filter
            )

            return {
                "success": True,
                "subjects": overview["subjects"],
                "stats": overview["stats"],
                "subject_filter": subject_filter,
                "subtopic_filter": subtopic_filter,
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def save_quiz_questions(
        self,
        subject: str,
        subtopic: str,
        questions: List[Dict],
        quiz_type: str = "initial",
    ) -> Dict[str, Any]:
        """Save quiz questions (initial or pool)."""
        try:
            if quiz_type == "initial":
                quiz_data = {
                    "quiz_title": f"{subject.title()} - {subtopic.title()} Quiz",
                    "questions": questions,
                    "updated_date": "2025-10-02",
                }
                success = self.data_service.save_quiz_data(subject, subtopic, quiz_data)

            elif quiz_type == "pool":
                success = self.data_service.save_question_pool(
                    subject, subtopic, questions
                )

            else:
                return {
                    "success": False,
                    "error": "Invalid quiz type. Must be 'initial' or 'pool'",
                }

            if success:
                return {
                    "success": True,
                    "message": f"{quiz_type.title()} questions saved successfully",
                }
            else:
                return {"success": False, "error": "Failed to save questions"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============================================================================
    # EXPORT / IMPORT OPERATIONS
    # ============================================================================

    def export_all_content(self) -> Dict[str, Any]:
        """Compile a JSON snapshot for every subject, subtopic, and resource."""
        data_root = self.data_service.data_root_path
        loader = self.data_service.data_loader

        subjects = loader.discover_subjects()
        export_payload: Dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "subjects_index": None,
            "subjects": {},
        }

        subjects_index_path = os.path.join(data_root, "subjects.json")
        if os.path.exists(subjects_index_path):
            with open(subjects_index_path, "r", encoding="utf-8") as index_file:
                export_payload["subjects_index"] = json.load(index_file)

        for subject_id, subject_info in subjects.items():
            subject_block: Dict[str, Any] = {
                "info": loader.load_subject_info(subject_id) or {},
                "config": loader.load_subject_config(subject_id) or {},
                "meta": subject_info,
                "subtopics": {},
            }

            # Determine known subtopics from config and filesystem
            config_subtopics = (
                subject_block["config"].get("subtopics", {})
                if isinstance(subject_block.get("config"), dict)
                else {}
            )

            subject_dir = os.path.join(data_root, "subjects", subject_id)
            filesystem_subtopics = []
            if os.path.isdir(subject_dir):
                filesystem_subtopics = [
                    name
                    for name in os.listdir(subject_dir)
                    if os.path.isdir(os.path.join(subject_dir, name))
                ]

            subtopic_ids = set(list(config_subtopics.keys()) + filesystem_subtopics)

            for subtopic_id in sorted(subtopic_ids):
                subtopic_block: Dict[str, Any] = {}

                lesson_plans = loader.load_lesson_plans(subject_id, subtopic_id)
                if lesson_plans:
                    subtopic_block["lesson_plans"] = lesson_plans

                quiz_data = loader.load_quiz_data(subject_id, subtopic_id)
                if quiz_data:
                    subtopic_block["quiz_data"] = quiz_data

                pool_data = loader.load_question_pool(subject_id, subtopic_id)
                if pool_data:
                    subtopic_block["question_pool"] = pool_data

                videos_data = loader.load_videos(subject_id, subtopic_id)
                if videos_data:
                    subtopic_block["videos"] = videos_data

                if subtopic_block:
                    subject_block["subtopics"][subtopic_id] = subtopic_block

            export_payload["subjects"][subject_id] = subject_block

        return export_payload

    def import_all_content(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an exported JSON snapshot back to disk."""
        try:
            subjects = payload.get("subjects")
            if not isinstance(subjects, dict) or not subjects:
                return {
                    "success": False,
                    "error": "No subjects provided in import data.",
                }

            data_root = self.data_service.data_root_path

            for subject_id, subject_payload in subjects.items():
                subject_dir = os.path.join(data_root, "subjects", subject_id)
                os.makedirs(subject_dir, exist_ok=True)

                subject_info = subject_payload.get("info")
                if isinstance(subject_info, dict):
                    with open(
                        os.path.join(subject_dir, "subject_info.json"),
                        "w",
                        encoding="utf-8",
                    ) as info_file:
                        json.dump(subject_info, info_file, indent=2, ensure_ascii=False)

                subject_config = subject_payload.get("config")
                if isinstance(subject_config, dict):
                    with open(
                        os.path.join(subject_dir, "subject_config.json"),
                        "w",
                        encoding="utf-8",
                    ) as config_file:
                        json.dump(
                            subject_config, config_file, indent=2, ensure_ascii=False
                        )

                subtopics = subject_payload.get("subtopics", {})
                if isinstance(subtopics, dict):
                    for subtopic_id, subtopic_payload in subtopics.items():
                        subtopic_dir = os.path.join(subject_dir, subtopic_id)
                        os.makedirs(subtopic_dir, exist_ok=True)

                        file_map = {
                            "lesson_plans": "lesson_plans.json",
                            "quiz_data": "quiz_data.json",
                            "question_pool": "question_pool.json",
                            "videos": "videos.json",
                        }

                        for key, filename in file_map.items():
                            if key in subtopic_payload:
                                with open(
                                    os.path.join(subtopic_dir, filename),
                                    "w",
                                    encoding="utf-8",
                                ) as target_file:
                                    json.dump(
                                        subtopic_payload[key],
                                        target_file,
                                        indent=2,
                                        ensure_ascii=False,
                                    )

            subjects_index = payload.get("subjects_index")
            if subjects_index is not None:
                with open(
                    os.path.join(data_root, "subjects.json"),
                    "w",
                    encoding="utf-8",
                ) as index_file:
                    json.dump(subjects_index, index_file, indent=2, ensure_ascii=False)

            # Clear any cached data so fresh content is picked up
            self.data_service.clear_cache()

            return {
                "success": True,
                "message": f"Imported data for {len(subjects)} subject(s) successfully.",
            }

        except Exception as exc:
            print(f"Error importing dataset: {exc}")
            return {"success": False, "error": str(exc)}

    # ============================================================================
    # OVERRIDE AND TESTING FUNCTIONALITY
    # ============================================================================

    def toggle_override(self) -> Dict[str, Any]:
        """Toggle admin override status."""
        try:
            new_status = self.progress_service.toggle_admin_override()

            return {
                "success": True,
                "admin_override": new_status,
                "message": f"Admin override {'enabled' if new_status else 'disabled'}",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_override(self, enabled: bool) -> Dict[str, Any]:
        """Explicitly set the admin override status."""
        try:
            status = self.progress_service.set_admin_override(enabled)
            return {
                "success": True,
                "admin_override": status,
                "message": f"Admin override {'enabled' if status else 'disabled'}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_override_status(self) -> Dict[str, Any]:
        """Get current admin override status."""
        try:
            return {
                "success": True,
                "admin_override": self.progress_service.get_admin_override_status(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Backwards compatibility helpers -------------------------------------------------

    def toggle_admin_override(self) -> Dict[str, Any]:
        """Backward compatible alias for toggle_override."""
        return self.toggle_override()

    def get_admin_status(self) -> Dict[str, Any]:
        """Backward compatible alias for check_override_status."""
        return self.check_override_status()

    def admin_mark_complete(self, subject: str, subtopic: str) -> Dict[str, Any]:
        """Mark a topic as complete for admin override."""
        try:
            success = self.progress_service.admin_mark_complete(subject, subtopic)

            if success:
                return {
                    "success": True,
                    "message": f"Topic {subject}/{subtopic} marked as complete",
                }
            else:
                return {"success": False, "error": "Failed to mark topic as complete"}

        except Exception as e:
            return {"success": False, "error": str(e)}
