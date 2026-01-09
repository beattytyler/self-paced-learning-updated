"""Data Service Module

Handles all data loading, saving, and file operations for the learning platform.
Extracts data access logic from the main application routes.
"""

import os
import json
from utils.data_loader import DataLoader
from typing import Dict, List, Optional, Any


def _default_data_root() -> str:
    """Return the default absolute path to the bundled data directory."""

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    return os.path.join(project_root, "data")


class DataService:
    """Service class for handling all data operations."""

    def __init__(self, data_root_path: Optional[str] = None):
        """Initialize the data service with the root data path.

        Args:
            data_root_path: Optional explicit path to the data directory. When
                omitted the service falls back to the repository's bundled
                ``data`` directory.  This mirrors the historic behaviour used
                throughout the tests, allowing ``DataService()`` to work
                without requiring a caller-provided path.
        """

        resolved_path = data_root_path or _default_data_root()
        self.data_root_path = os.path.abspath(resolved_path)
        self.data_loader = DataLoader(self.data_root_path)

    # ============================================================================
    # QUIZ DATA OPERATIONS
    # ============================================================================

    def get_quiz_data(self, subject: str, subtopic: str) -> Optional[List[Dict]]:
        """Load quiz questions for a specific subject/subtopic."""
        return self.data_loader.load_quiz_data(subject, subtopic)

    def get_quiz_title(self, subject: str, subtopic: str) -> str:
        """Get quiz title for a subject/subtopic."""
        return self.data_loader.get_quiz_title(subject, subtopic)

    def save_quiz_data(self, subject: str, subtopic: str, quiz_data: Dict) -> bool:
        """Save quiz data to file."""
        try:
            quiz_file_path = os.path.join(
                self.data_root_path, "subjects", subject, subtopic, "quiz_data.json"
            )

            # Ensure directory exists
            os.makedirs(os.path.dirname(quiz_file_path), exist_ok=True)

            with open(quiz_file_path, "w", encoding="utf-8") as f:
                json.dump(quiz_data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error saving quiz data: {e}")
            return False

    def get_question_pool_questions(
        self, subject: str, subtopic: str
    ) -> Optional[List[Dict]]:
        """Get question pool questions for remedial quizzes."""
        return self.data_loader.get_question_pool_questions(subject, subtopic)

    def save_question_pool(
        self, subject: str, subtopic: str, questions: List[Dict]
    ) -> bool:
        """Save question pool data to file."""
        try:
            pool_file_path = os.path.join(
                self.data_root_path, "subjects", subject, subtopic, "question_pool.json"
            )

            # Ensure directory exists
            os.makedirs(os.path.dirname(pool_file_path), exist_ok=True)

            pool_data = {"questions": questions, "updated_date": "2025-10-02"}

            with open(pool_file_path, "w", encoding="utf-8") as f:
                json.dump(pool_data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error saving question pool: {e}")
            return False

    # ============================================================================
    # LESSON DATA OPERATIONS
    # ============================================================================

    @staticmethod
    def _is_lesson_listed(lesson: Dict[str, Any]) -> bool:
        """Return True if the lesson should be visible to learners (not hidden/unavailable)."""
        if not lesson:
            return False

        visibility = str(lesson.get("visibility", "") or "").strip().lower()
        status = str(lesson.get("status", "") or "").strip().lower()

        if visibility in {"unlisted", "hidden", "private"}:
            return False
        if status in {
            "unlisted",
            "inactive",
            "unavailable",
            "hidden",
            "archived",
            "disabled",
            "draft",
        }:
            return False
        if lesson.get("unlisted") is True:
            return False
        if lesson.get("listed") is False:
            return False
        if lesson.get("is_listed") is False:
            return False

        return True

    def get_lesson_plans(
        self, subject: str, subtopic: str, include_unlisted: bool = True
    ) -> Optional[List[Dict]]:
        """
        Load lesson plans for a specific subject/subtopic.

        Set ``include_unlisted`` to False to hide lessons marked hidden/unlisted/unavailable
        and to ignore subtopics whose status is not active for learner-facing views.
        """
        if not include_unlisted:
            try:
                subject_config = self.load_subject_config(subject) or {}
                subtopic_status = (
                    subject_config.get("subtopics", {})
                    .get(subtopic, {})
                    .get("status", "")
                )
                subtopic_status = (
                    "" if subtopic_status is None else str(subtopic_status)
                ).strip().lower()
                if subtopic_status and subtopic_status != "active":
                    return []
            except Exception:
                # If status cannot be determined, fall back to loading the data.
                pass

        lesson_data = self.data_loader.load_lesson_plans(subject, subtopic)

        if not lesson_data or "lessons" not in lesson_data:
            return []

        lessons = lesson_data["lessons"]

        # Convert lessons object to array if needed
        lesson_list: List[Dict[str, Any]] = []

        if isinstance(lessons, dict):
            # Convert from {id: lesson_data} to [lesson_data] format
            for lesson_id, lesson_content in lessons.items():
                if not isinstance(lesson_content, dict):
                    continue
                lesson_copy = dict(lesson_content)
                lesson_copy["id"] = lesson_copy.get("id", lesson_id)
                lesson_list.append(lesson_copy)
        elif isinstance(lessons, list):
            for index, lesson_content in enumerate(lessons):
                if not isinstance(lesson_content, dict):
                    continue
                lesson_copy = dict(lesson_content)
                if "id" not in lesson_copy:
                    # Maintain legacy ordering-based identifiers for list payloads
                    lesson_copy["id"] = lesson_copy.get("lesson_id") or f"lesson_{index + 1}"
                lesson_list.append(lesson_copy)

        # Sort by order if available
        lesson_list.sort(key=lambda x: x.get("order", 999))

        if not include_unlisted:
            lesson_list = [
                lesson for lesson in lesson_list if self._is_lesson_listed(lesson)
            ]

        return lesson_list

    def get_all_lessons(self) -> List[Dict]:
        """Get all lessons across all subjects and subtopics."""
        lessons = []
        subjects = self.data_loader.discover_subjects()

        for subject_id, subject_info in subjects.items():
            subject_config = self.data_loader.load_subject_config(subject_id)

            if subject_config and "subtopics" in subject_config:
                for subtopic_id in subject_config["subtopics"].keys():
                    subject_lessons = self.get_lesson_plans(subject_id, subtopic_id)

                    if subject_lessons:
                        for lesson in subject_lessons:
                            lesson["subject"] = subject_id
                            lesson["subtopic"] = subtopic_id
                            lesson["subject_name"] = subject_info.get(
                                "name", subject_id.title()
                            )

                            # Get subtopic name
                            subtopic_name = subject_config["subtopics"][
                                subtopic_id
                            ].get("name", subtopic_id.title())
                            lesson["subtopic_name"] = subtopic_name

                            lessons.append(lesson)

        return lessons

    def save_lesson_to_file(
        self, subject: str, subtopic: str, lesson_id: str, lesson_data: Dict
    ) -> bool:
        """Save a lesson to the lesson_plans.json file."""
        try:
            lesson_file_path = os.path.join(
                self.data_root_path, "subjects", subject, subtopic, "lesson_plans.json"
            )

            # Load existing lessons or create new structure
            existing_data: Dict[str, Any] = {}
            lessons_container: Any = []
            lessons_container_type = "list"
            if os.path.exists(lesson_file_path):
                with open(lesson_file_path, "r", encoding="utf-8") as f:
                    existing_raw = json.load(f)
                    # Handle both old format (array) and new format (dict with lessons key)
                    if isinstance(existing_raw, list):
                        lessons_container = existing_raw
                    elif isinstance(existing_raw, dict):
                        existing_data = existing_raw
                        lessons_container = existing_raw.get("lessons", [])
                        if isinstance(lessons_container, dict):
                            lessons_container_type = "dict"
                    else:
                        lessons_container = []

            # Always include the lesson identifier in the payload we persist.
            serialised_lesson = dict(lesson_data)
            serialised_lesson["id"] = lesson_id

            if lessons_container_type == "dict":
                # Preserve mapping-style lesson payloads
                lessons_container = dict(lessons_container or {})
                lessons_container[lesson_id] = serialised_lesson
            else:
                # Normalise list payloads to avoid non-dict entries and preserve sequence
                normalised_lessons = [
                    lesson for lesson in lessons_container if isinstance(lesson, dict)
                ]

                # Replace in place if it exists; otherwise append to preserve existing ordering
                replaced = False
                for index, lesson in enumerate(normalised_lessons):
                    if lesson.get("id") == lesson_id:
                        normalised_lessons[index] = serialised_lesson
                        replaced = True
                        break

                if not replaced:
                    normalised_lessons.append(serialised_lesson)

                lessons_container = normalised_lessons

            # Create the complete lesson plans structure and preserve any extra metadata
            lesson_plans_data: Dict[str, Any] = (
                dict(existing_data) if isinstance(existing_data, dict) else {}
            )
            lesson_plans_data["lessons"] = lessons_container
            lesson_plans_data["updated_date"] = "2025-10-02"

            # Ensure directory exists
            os.makedirs(os.path.dirname(lesson_file_path), exist_ok=True)

            with open(lesson_file_path, "w", encoding="utf-8") as f:
                json.dump(lesson_plans_data, f, indent=2, ensure_ascii=False)

            # Clear cached lesson data so future reads pick up the updates.
            try:
                self.data_loader.clear_cache_for_subject_subtopic(subject, subtopic)
            except AttributeError:
                # Older DataLoader implementations may not provide cache clearing.
                pass

            return True
        except Exception as e:
            print(f"Error saving lesson: {e}")
            return False

    def delete_lesson_from_file(
        self, subject: str, subtopic: str, lesson_id: str
    ) -> bool:
        """Delete a lesson from the lesson_plans.json file."""
        try:
            lesson_file_path = os.path.join(
                self.data_root_path, "subjects", subject, subtopic, "lesson_plans.json"
            )

            if not os.path.exists(lesson_file_path):
                return False

            with open(lesson_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            lessons = data.get("lessons", [])
            lessons_container_type = "dict" if isinstance(lessons, dict) else "list"

            if lessons_container_type == "dict":
                if lesson_id not in lessons:
                    return False  # Lesson not found
                # Create a copy so we don't mutate the original mapping
                lessons = {
                    key: value for key, value in lessons.items() if key != lesson_id
                }
            else:
                original_count = len(lessons) if isinstance(lessons, list) else 0
                lessons = (
                    [
                        lesson
                        for lesson in (lessons if isinstance(lessons, list) else [])
                        if isinstance(lesson, dict) and lesson.get("id") != lesson_id
                    ]
                )
                if len(lessons) == original_count:
                    return False  # Lesson not found

            # Update the data structure while preserving other metadata
            data["lessons"] = lessons
            data["updated_date"] = "2025-10-02"

            with open(lesson_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            try:
                self.data_loader.clear_cache_for_subject_subtopic(subject, subtopic)
            except AttributeError:
                pass

            return True
        except Exception as e:
            print(f"Error deleting lesson: {e}")
            return False

    def get_lesson_map(self, subject: str, subtopic: str) -> Dict[str, Dict[str, Any]]:
        """Return lessons indexed by their identifier for quick lookup."""

        lesson_map: Dict[str, Dict[str, Any]] = {}
        lessons = self.get_lesson_plans(subject, subtopic) or []

        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue

            lesson_id = lesson.get("id")
            if not lesson_id:
                continue

            lesson_map[lesson_id] = lesson

        return lesson_map

    # ============================================================================
    # VIDEO DATA OPERATIONS
    # ============================================================================

    def get_video_data(self, subject: str, subtopic: str) -> Optional[Dict]:
        """Load and normalise video data for a specific subject/subtopic."""

        raw_data = self.data_loader.load_videos(subject, subtopic) or {}
        videos_payload = raw_data.get("videos", {})

        video_list: List[Dict[str, Any]] = []
        video_map: Dict[str, Dict[str, Any]] = {}

        if isinstance(videos_payload, dict):
            for index, (video_id, video) in enumerate(videos_payload.items()):
                normalised = {"id": video_id, **(video or {})}
                video_list.append(normalised)
                video_map[video_id] = normalised
        elif isinstance(videos_payload, list):
            for index, video in enumerate(videos_payload):
                candidate_id = None
                if isinstance(video, dict):
                    candidate_id = (
                        video.get("id")
                        or video.get("video_id")
                        or video.get("topic_key")
                    )
                video_id = candidate_id or f"video_{index + 1}"
                normalised = {"id": video_id, **(video or {})}
                video_list.append(normalised)
                video_map[video_id] = normalised

        normalised_data = {**raw_data, "videos": video_list}
        if video_map:
            normalised_data["video_map"] = video_map

        return normalised_data

    def get_video_by_topic(
        self, subject: str, subtopic: str, topic_key: str
    ) -> Optional[Dict]:
        """Get specific video by topic key."""
        video_data = self.get_video_data(subject, subtopic) or {}
        video_map = video_data.get("video_map", {})

        if topic_key in video_map:
            return video_map[topic_key]

        for video in video_data.get("videos", []):
            if not isinstance(video, dict):
                continue
            if video.get("topic_key") == topic_key or video.get("id") == topic_key:
                return video

        return None

    # ============================================================================
    # SUBJECT AND SUBTOPIC OPERATIONS
    # ============================================================================

    def discover_subjects(self) -> Dict[str, Dict]:
        """Discover all available subjects."""
        return self.data_loader.discover_subjects()

    def load_subject_config(self, subject: str) -> Optional[Dict]:
        """Load subject configuration."""
        return self.data_loader.load_subject_config(subject)

    def load_subject_info(self, subject: str) -> Optional[Dict]:
        """Load subject information."""
        return self.data_loader.load_subject_info(subject)

    def validate_subject_subtopic(self, subject: str, subtopic: str) -> bool:
        """Validate that a subject/subtopic combination exists."""
        return self.data_loader.validate_subject_subtopic(subject, subtopic)

    def create_subject(self, subject_id: str, subject_data: Dict) -> bool:
        """Create a new subject with its directory structure and files."""
        try:
            subject_dir = os.path.join(self.data_root_path, "subjects", subject_id)

            # Check if subject already exists
            if os.path.exists(subject_dir):
                return False

            # Create subject directory
            os.makedirs(subject_dir, exist_ok=True)

            # Create subject_info.json
            subject_info_path = os.path.join(subject_dir, "subject_info.json")
            with open(subject_info_path, "w", encoding="utf-8") as f:
                json.dump(subject_data["info"], f, indent=2, ensure_ascii=False)

            # Create subject_config.json
            subject_config_path = os.path.join(subject_dir, "subject_config.json")
            with open(subject_config_path, "w", encoding="utf-8") as f:
                json.dump(subject_data["config"], f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error creating subject: {e}")
            return False

    def update_subject(
        self,
        subject_id: str,
        subject_info: Optional[Dict] = None,
        subtopics: Optional[Dict] = None,
        allowed_tags: Optional[List[str]] = None,
        rename_subtopic: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Update the configuration files for an existing subject.

        This method persists changes to ``subject_info.json`` and
        ``subject_config.json`` using the resolved absolute data path so the
        caller does not need to worry about the current working directory.
        """

        if not subject_id:
            raise ValueError("subject_id is required")

        subject_dir = os.path.join(self.data_root_path, "subjects", subject_id)
        if not os.path.isdir(subject_dir):
            raise FileNotFoundError(f"Subject directory not found: {subject_dir}")

        updated = False

        try:
            if subject_info is not None:
                if not isinstance(subject_info, dict):
                    raise TypeError("subject_info must be a dictionary when provided")

                subject_info_path = os.path.join(subject_dir, "subject_info.json")

                with open(subject_info_path, "w", encoding="utf-8") as handle:
                    json.dump(subject_info, handle, indent=2, ensure_ascii=False)

                updated = True

            config_updates: Dict[str, Any] = {}

            if subtopics is not None:
                if not isinstance(subtopics, dict):
                    raise TypeError("subtopics must be a dictionary when provided")
                config_updates["subtopics"] = subtopics

            if allowed_tags is not None:
                if not isinstance(allowed_tags, list):
                    raise TypeError("allowed_tags must be a list when provided")
                config_updates["allowed_tags"] = allowed_tags

            subject_config_path = os.path.join(subject_dir, "subject_config.json")

            existing_config: Dict[str, Any] = {}
            if os.path.exists(subject_config_path):
                with open(subject_config_path, "r", encoding="utf-8") as handle:
                    try:
                        existing_config = json.load(handle) or {}
                    except json.JSONDecodeError:
                        existing_config = {}

            # Handle subtopic rename if requested
            existing_subtopics = existing_config.get("subtopics", {})
            effective_subtopics = (
                dict(subtopics) if isinstance(subtopics, dict) else dict(existing_subtopics)
            )

            if rename_subtopic:
                if not isinstance(rename_subtopic, dict):
                    raise TypeError("rename_subtopic must be a dictionary when provided")
                old_id = (rename_subtopic.get("from") or "").strip()
                new_id = (rename_subtopic.get("to") or "").strip()

                if not old_id or not new_id:
                    raise ValueError("Both 'from' and 'to' subtopic identifiers are required for renaming")

                if old_id == new_id:
                    # No-op rename, proceed with normal update
                    rename_subtopic = None
                else:
                    if old_id not in existing_subtopics:
                        raise ValueError(f"Subtopic '{old_id}' does not exist and cannot be renamed")
                    if new_id in existing_subtopics:
                        raise ValueError(f"Subtopic '{new_id}' already exists; choose a different identifier")

                    # Move subtopic directory if it exists
                    old_dir = os.path.join(subject_dir, old_id)
                    new_dir = os.path.join(subject_dir, new_id)
                    if os.path.exists(old_dir):
                        os.rename(old_dir, new_dir)
                    else:
                        os.makedirs(new_dir, exist_ok=True)

                    # Re-key the subtopic entry in the effective payload
                    subtopic_payload = effective_subtopics.pop(
                        old_id, existing_subtopics.get(old_id, {})
                    )
                    effective_subtopics[new_id] = subtopic_payload

                    # Update prerequisites that reference the old subtopic ID
                    for payload in effective_subtopics.values():
                        if not isinstance(payload, dict):
                            continue
                        prereqs = payload.get("prerequisites", [])
                        if isinstance(prereqs, list) and old_id in prereqs:
                            payload["prerequisites"] = [
                                new_id if prereq == old_id else prereq for prereq in prereqs
                            ]

                    updated = True

            # If subtopics are being updated (or inferred), ensure directories exist and prepare config
            if subtopics is not None or rename_subtopic:
                for subtopic_id in effective_subtopics.keys():
                    subtopic_dir = os.path.join(subject_dir, subtopic_id)
                    if not os.path.exists(subtopic_dir):
                        os.makedirs(subtopic_dir, exist_ok=True)

                        # Initialize with proper lesson_plans.json structure to make it valid
                        lesson_plans_path = os.path.join(subtopic_dir, "lesson_plans.json")
                        if not os.path.exists(lesson_plans_path):
                            with open(lesson_plans_path, "w", encoding="utf-8") as f:
                                json.dump(
                                    {"lessons": [], "updated_date": "2025-10-15"},
                                    f,
                                    indent=2,
                                    ensure_ascii=False,
                                )

                config_updates["subtopics"] = effective_subtopics

            if config_updates:
                existing_config.update(config_updates)

                with open(subject_config_path, "w", encoding="utf-8") as handle:
                    json.dump(existing_config, handle, indent=2, ensure_ascii=False)

                updated = True

            if updated:
                try:
                    self.clear_cache_for_subject(subject_id)
                except Exception:
                    # Cache clearing is best-effort; failures should not block the
                    # update because the persisted files are already written.
                    pass

            return updated
        except Exception:
            # Re-raise so callers can return appropriate error responses while
            # preserving the underlying exception context.
            raise

    def delete_subject(self, subject_id: str) -> bool:
        """Delete a subject and all its associated data."""
        try:
            import shutil

            subject_dir = os.path.join(self.data_root_path, "subjects", subject_id)

            if os.path.exists(subject_dir):
                shutil.rmtree(subject_dir)
                return True

            return False
        except Exception as e:
            print(f"Error deleting subject: {e}")
            return False

    def delete_subtopic(self, subject: str, subtopic_id: str) -> bool:
        """Delete a subtopic and all its associated data.

        This removes:
        1. The subtopic directory and all files within it
        2. The subtopic entry from subject_config.json

        Args:
            subject: The subject identifier
            subtopic_id: The subtopic identifier to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            import shutil

            # Remove the subtopic directory
            subtopic_dir = os.path.join(
                self.data_root_path, "subjects", subject, subtopic_id
            )
            if os.path.exists(subtopic_dir):
                shutil.rmtree(subtopic_dir)

            # Update subject_config.json to remove the subtopic
            config_path = os.path.join(
                self.data_root_path, "subjects", subject, "subject_config.json"
            )

            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # Remove subtopic from config
                subtopics = config.get("subtopics", {})
                if subtopic_id in subtopics:
                    del subtopics[subtopic_id]
                    config["subtopics"] = subtopics

                    # Save updated config
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)

            # Clear cache for this subject
            try:
                self.clear_cache_for_subject(subject)
            except Exception:
                pass

            return True

        except Exception as e:
            print(f"Error deleting subtopic: {e}")
            return False

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    def get_subject_allowed_tags(self, subject: str) -> List[str]:
        """Get configured allowed tags for a subject."""
        try:
            tags = self.data_loader.get_subject_keywords(subject)
            return [tag for tag in tags if isinstance(tag, str)]
        except Exception as exc:
            print(f"Error retrieving allowed tags for subject {subject}: {exc}")
            return []

    def get_subject_tags(self, subject: str) -> List[str]:
        """Get all available tags for a subject.

        Combines the explicit allowed tag pool with tags found on lessons so admins
        can pick from curated and already-used values.
        """
        tag_lookup: Dict[str, str] = {}

        # Start with allowed tags configured on the subject
        subject_config = self.load_subject_config(subject) or {}
        allowed_tags = subject_config.get(
            "allowed_tags", subject_config.get("allowed_keywords", [])
        )
        for tag in allowed_tags or []:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if cleaned:
                tag_lookup.setdefault(cleaned.lower(), cleaned)

        # Merge in lesson-level tags
        if subject_config and "subtopics" in subject_config:
            for subtopic_id in subject_config["subtopics"].keys():
                lessons = self.get_lesson_plans(subject, subtopic_id)
                if lessons:
                    for lesson in lessons:
                        lesson_tags = lesson.get("tags", [])
                        if not isinstance(lesson_tags, list):
                            continue
                        for tag in lesson_tags:
                            if not isinstance(tag, str):
                                continue
                            cleaned = tag.strip()
                            if cleaned:
                                tag_lookup.setdefault(cleaned.lower(), cleaned)

        return sorted(tag_lookup.values(), key=lambda value: value.lower())

    def add_subject_tag(self, subject: str, tag: str) -> Optional[List[str]]:
        """Add a new tag to a subject's allowed tag pool and return the updated list."""
        if not isinstance(tag, str):
            raise TypeError("tag must be a string")

        cleaned_tag = tag.strip()
        if not cleaned_tag:
            raise ValueError("tag cannot be empty")

        subject_config = self.load_subject_config(subject)
        if not subject_config:
            return None

        allowed_tags = subject_config.get(
            "allowed_tags", subject_config.get("allowed_keywords", [])
        ) or []

        tag_lookup: Dict[str, str] = {
            str(existing).strip().lower(): str(existing).strip()
            for existing in allowed_tags
            if isinstance(existing, str) and str(existing).strip()
        }

        tag_lookup.setdefault(cleaned_tag.lower(), cleaned_tag)

        updated_tags = sorted(tag_lookup.values(), key=lambda value: value.lower())

        if not self.update_subject(subject, allowed_tags=updated_tags):
            return None

        try:
            self.clear_cache_for_subject(subject)
        except Exception:
            pass

        return updated_tags

    def remove_subject_tag(self, subject: str, tag: str) -> Optional[List[str]]:
        """Remove a tag from a subject's allowed tag pool and return the updated list."""
        if not isinstance(tag, str):
            raise TypeError("tag must be a string")

        cleaned_tag = tag.strip()
        if not cleaned_tag:
            raise ValueError("tag cannot be empty")

        subject_config = self.load_subject_config(subject)
        if not subject_config:
            return None

        allowed_tags = subject_config.get(
            "allowed_tags", subject_config.get("allowed_keywords", [])
        ) or []

        tag_lookup: Dict[str, str] = {
            str(existing).strip().lower(): str(existing).strip()
            for existing in allowed_tags
            if isinstance(existing, str) and str(existing).strip()
        }

        lowered = cleaned_tag.lower()
        if lowered in tag_lookup:
            del tag_lookup[lowered]

        updated_tags = sorted(tag_lookup.values(), key=lambda value: value.lower())

        if not self.update_subject(subject, allowed_tags=updated_tags):
            return None

        try:
            self.clear_cache_for_subject(subject)
        except Exception:
            pass

        return updated_tags

    def find_lessons_by_tags(
        self, subject: str, required_tags: List[str], include_unlisted: bool = True
    ) -> List[Dict]:
        """Find lessons that contain all required tags."""
        matching_lessons = []
        subject_config = self.load_subject_config(subject)

        if subject_config and "subtopics" in subject_config:
            for subtopic_id in subject_config["subtopics"].keys():
                lessons = self.get_lesson_plans(
                    subject, subtopic_id, include_unlisted=include_unlisted
                )

                if lessons:
                    for lesson in lessons:
                        lesson_tags = lesson.get("tags", [])

                        # Check if lesson contains all required tags
                        if all(tag in lesson_tags for tag in required_tags):
                            lesson_copy = lesson.copy()
                            lesson_copy["subject"] = subject
                            lesson_copy["subtopic"] = subtopic_id
                            matching_lessons.append(lesson_copy)

        return matching_lessons

    # ============================================================================
    # CACHE OPERATIONS
    # ============================================================================

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.data_loader.clear_cache()

    def clear_cache_for_subject_subtopic(self, subject: str, subtopic: str) -> None:
        """Clear cache for specific subject/subtopic."""
        self.data_loader.clear_cache_for_subject_subtopic(subject, subtopic)

    def clear_cache_for_subject(self, subject: str) -> None:
        """Clear all cached data for a subject."""
        self.data_loader.clear_cache_for_subject(subject)
