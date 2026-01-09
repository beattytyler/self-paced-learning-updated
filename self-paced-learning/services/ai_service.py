"""AI Service Module

Handles all AI-powered features including OpenAI integration, quiz analysis,
and learning recommendations. Extracts AI logic from the main application routes.
"""

import openai
import os
from typing import Dict, List, Optional, Any, Iterable, Set
import json
import re
import random

try:
    from openai import OpenAI as OpenAIClient
except ImportError:
    OpenAIClient = None


class AIService:
    """Service class for handling AI-powered features."""

    def __init__(self):
        """Initialize the AI service with OpenAI configuration."""
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.default_model = os.getenv("OPENAI_MODEL", "gpt-4")
        self.model = self.default_model  # Set model attribute for API calls
        self.client: Optional[Any] = None

        if self.api_key and OpenAIClient:
            try:
                self.client = OpenAIClient(api_key=self.api_key)
            except TypeError:
                self.client = OpenAIClient()
            except Exception as exc:
                print(f"Warning: failed to initialize OpenAI client: {exc}")
                self.client = None

        if self.api_key:
            try:
                openai.api_key = self.api_key
            except Exception:
                pass
        else:
            print("Warning: OPENAI_API_KEY not set. AI features will not work.")

    def is_available(self) -> bool:
        """Check if AI service is available (API key configured)."""
        return self.api_key is not None

    # ============================================================================
    # CORE AI API METHODS
    # ============================================================================

    def call_openai_api(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_message: Optional[str] = None,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        expect_json_output: bool = False,
    ) -> Optional[str]:
        """Helper function to call the OpenAI API with optional JSON expectations."""
        if not self.is_available():
            return None

        messages = [
            {
                "role": "system",
                "content": system_message or "You are a helpful educational assistant.",
            },
            {"role": "user", "content": prompt},
        ]

        model_to_use = model or getattr(self, "default_model", "gpt-4")

        kwargs = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if expect_json_output:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None

        if getattr(self, "client", None) and getattr(self.client, "chat", None):
            try:
                response = self.client.chat.completions.create(**kwargs)
                content = self._extract_content_from_response(response)
                if content:
                    return content.strip()
            except Exception as exc:
                last_error = exc

        for api_call in (
            lambda: openai.ChatCompletion.create(**kwargs),
            lambda: openai.chat.completions.create(**kwargs),
        ):
            try:
                response = api_call()
                content = self._extract_content_from_response(response)
                if content:
                    return content.strip()
            except AttributeError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

        if getattr(self, "client", None) and getattr(self.client, "responses", None):
            try:
                prompt_text = "\n".join(
                    message["content"] for message in messages if message.get("content")
                )
                response_kwargs = {
                    "model": model_to_use,
                    "input": prompt_text,
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
                response = self.client.responses.create(**response_kwargs)
                content = self._extract_content_from_response(response)
                if content:
                    return content.strip()
            except Exception as exc:
                last_error = exc

        if last_error:
            print(f"Error calling OpenAI API: {last_error}")
        return None

    def _extract_content_from_response(self, response: Any) -> Optional[str]:
        if not response:
            return None

        choices = getattr(response, "choices", None)
        if choices:
            first_choice = choices[0]
            message = getattr(first_choice, "message", None)
            if isinstance(message, dict):
                content = message.get("content")
            else:
                content = getattr(message, "content", None)
            text_value = self._flatten_content(content)
            if text_value:
                return text_value

            text_attr = getattr(first_choice, "text", None)
            if isinstance(text_attr, str):
                return text_attr

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = getattr(response, "output", None)
        if isinstance(output, list) and output:
            content = getattr(output[0], "content", None)
            text_value = self._flatten_content(content)
            if text_value:
                return text_value

        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            message = getattr(data[0], "message", None)
            if message:
                text_value = self._flatten_content(getattr(message, "content", None))
                if text_value:
                    return text_value

        if isinstance(response, dict):
            choices = response.get("choices")
            if choices:
                choice0 = choices[0] if choices else None
                message = choice0.get("message") if isinstance(choice0, dict) else None
                text_value = self._flatten_content(
                    message.get("content") if message else None
                )
                if text_value:
                    return text_value
        return None

    def _flatten_content(self, content: Any) -> Optional[str]:
        if not content:
            return None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
                    else:
                        content_value = item.get("content")
                        if isinstance(content_value, str):
                            parts.append(content_value)
            if parts:
                return "\n".join(part for part in parts if part)
        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            content_value = content.get("content")
            if isinstance(content_value, str):
                return content_value
        return None

    # ============================================================================
    # QUIZ ANALYSIS AND RECOMMENDATIONS
    # ============================================================================

    def analyze_quiz_performance(
        self, questions: List[Dict], answers: List[str], subject: str, subtopic: str
    ) -> Dict[str, Any]:
        """Analyze quiz performance and generate tag-aware recommendations."""
        from services import get_data_service

        total_questions = len(questions)
        normalized_answers = [
            str(answer) if answer is not None else "" for answer in answers
        ]
        correct_answers = 0
        submission_details: List[str] = []
        wrong_indices: List[int] = []
        wrong_tag_candidates: List[str] = []

        for idx, question in enumerate(questions):
            user_answer = (
                normalized_answers[idx] if idx < len(normalized_answers) else ""
            )
            question_type = (question.get("type") or "multiple_choice").strip().lower()
            status = "Incorrect"

            if question_type == "coding":
                status = "For AI Review"
            elif self._is_answer_correct(question, user_answer):
                status = "Correct"
                correct_answers += 1
            else:
                wrong_indices.append(idx)
                wrong_tag_candidates.extend(self._collect_question_tags(question))

            correct_answer_text = self._resolve_correct_answer(question)
            detail_lines = [
                f"Question {idx + 1} (Type: {question_type}): {question.get('question', 'N/A')}",
                "Student's Answer:",
                "---",
                user_answer if user_answer else "[No answer provided]",
                "---",
            ]
            if correct_answer_text:
                detail_lines.append(f"Correct Answer: {correct_answer_text}")
            detail_lines.append(f"Status: {status}")
            submission_details.append("\n".join(detail_lines) + "\n")

        score_percentage = (
            round((correct_answers / total_questions) * 100)
            if total_questions > 0
            else 0
        )

        analysis: Dict[str, Any] = {
            "score": {
                "correct": correct_answers,
                "total": total_questions,
                "percentage": score_percentage,
            },
            "weak_topics": [],
            "weak_tags": [],
            "weak_areas": [],
            "feedback": "",
            "ai_analysis": "",
            "recommendations": [],
            "submission_details": submission_details,
            "wrong_question_indices": wrong_indices,
            "allowed_tags": [],
            "used_ai": False,
        }

        try:
            data_service = get_data_service()
            allowed_tags = data_service.get_subject_allowed_tags(subject)
        except Exception as exc:
            print(f"Error getting allowed tags for {subject}: {exc}")
            allowed_tags = []

        allowed_lookup = {
            str(tag).lower(): str(tag) for tag in allowed_tags if isinstance(tag, str)
        }
        analysis["allowed_tags"] = allowed_tags

        normalized_missed_tags = self._normalize_tags(wrong_tag_candidates)

        fallback_tags = self._filter_allowed_tags(wrong_tag_candidates, allowed_lookup)
        if not fallback_tags:
            fallback_tags = normalized_missed_tags

        submission_text = (
            "".join(submission_details)
            if submission_details
            else "[No submission details available]"
        )
        system_message = (
            "You are an expert instructor. Your task is to analyze a student's quiz performance, "
            "classify their errors against a predefined list of topics, and evaluate their submitted code when provided."
        )
        allowed_tags_str = json.dumps(allowed_tags) if allowed_tags else "[]"

        prompt_parts = [
            "You are analyzing a student's quiz submission which includes multiple choice, fill-in-the-blank, and coding questions.",
            "Based on the incorrect answers and their submitted code, identify the concepts they are weak in.",
            f"You MUST choose the weak concepts from this predefined list ONLY: {allowed_tags_str}",
            "For coding questions marked 'For AI Review', evaluate if the student's code:",
            "1. Correctly solves the problem",
            "2. Uses appropriate syntax and conventions",
            "3. Demonstrates understanding of the underlying concepts",
            "Compare their code with the provided sample solution when available.",
            "Provide your analysis as a single JSON object with two keys:",
            ' - "detailed_feedback": (string) Your textual analysis, including specific feedback on coding attempts, what they did well, and areas for improvement.',
            ' - "weak_concept_tags": (JSON list of strings) The list of weak concepts from the ALLOWED TAGS list. If there are no weaknesses, provide an empty list [].',
            f"Overall score: {correct_answers}/{total_questions} correct ({score_percentage}%).",
            "Here is the student's submission:",
            "--- START OF SUBMISSION ---",
            submission_text,
            "--- END OF SUBMISSION ---",
        ]
        prompt = "\n".join(prompt_parts)

        ai_response = None
        if self.is_available():
            ai_response = self.call_openai_api(
                prompt,
                model=getattr(self, "default_model", "gpt-4"),
                system_message=system_message,
                max_tokens=1500,
                temperature=0.1,
                expect_json_output=True,
            )

        analysis["raw_ai_response"] = ai_response

        analysis["missed_tags"] = normalized_missed_tags

        if ai_response:
            parsed_response = self._extract_json_object(ai_response)
            if parsed_response:
                candidate_tags = parsed_response.get("weak_concept_tags") or []
                if isinstance(candidate_tags, str):
                    candidate_tags = [candidate_tags]
                validated_tags = self._filter_allowed_tags(
                    candidate_tags, allowed_lookup
                )
                if not validated_tags:
                    validated_tags = fallback_tags
                feedback = (
                    parsed_response.get("detailed_feedback")
                    or parsed_response.get("feedback")
                    or ""
                )

                analysis["weak_topics"] = validated_tags
                analysis["weak_tags"] = validated_tags
                analysis["weak_areas"] = validated_tags
                analysis["feedback"] = feedback
                analysis["ai_analysis"] = feedback
                analysis["used_ai"] = True
            else:
                analysis["weak_topics"] = fallback_tags
                analysis["weak_tags"] = fallback_tags
                analysis["weak_areas"] = fallback_tags
        else:
            analysis["weak_topics"] = fallback_tags
            analysis["weak_tags"] = fallback_tags
            analysis["weak_areas"] = fallback_tags

        if not analysis["feedback"]:
            if fallback_tags:
                analysis["feedback"] = (
                    f"You answered {correct_answers} out of {total_questions} correctly ("
                    f"{score_percentage}%). Focus on reviewing: {', '.join(fallback_tags)}."
                )
            else:
                analysis["feedback"] = (
                    f"Excellent work scoring {score_percentage}%! Keep practicing to reinforce your understanding."
                )
            analysis["ai_analysis"] = analysis["feedback"]

        analysis["recommendations"] = self._generate_recommendations(
            score_percentage, analysis["weak_topics"], subject, subtopic
        )

        return analysis

    def _resolve_correct_answer(self, question: Dict[str, Any]) -> str:
        question_type = (question.get("type") or "multiple_choice").strip().lower()
        if question_type == "multiple_choice":
            options = question.get("options", []) or []
            answer_index = question.get("answer_index")
            if answer_index is None:
                answer_index = question.get("correct_answer_index")
            if isinstance(answer_index, int) and 0 <= answer_index < len(options):
                return str(options[answer_index])
            return str(question.get("correct_answer", ""))
        if question_type == "fill_in_the_blank":
            correct = question.get("correct_answer")
            if isinstance(correct, list):
                return ", ".join(str(value) for value in correct)
            return str(correct or question.get("answer", ""))
        if question_type == "coding":
            for key in ("sample_solution", "solution", "correct_answer"):
                value = question.get(key)
                if value:
                    return str(value)
            return ""
        return str(question.get("correct_answer", ""))

    def _is_answer_correct(self, question: Dict[str, Any], user_answer: str) -> bool:
        question_type = (question.get("type") or "multiple_choice").strip().lower()
        answer_text = self._resolve_correct_answer(question)
        user_clean = (user_answer or "").strip()
        if not user_clean:
            return False
        if question_type == "multiple_choice":
            return user_clean == answer_text.strip()
        if question_type == "fill_in_the_blank":
            acceptable = []
            if answer_text:
                acceptable.extend(
                    [
                        part.strip().lower()
                        for part in answer_text.split(",")
                        if part.strip()
                    ]
                )
            raw_list = question.get("correct_answers") or question.get(
                "acceptable_answers"
            )
            if isinstance(raw_list, list):
                acceptable.extend(
                    [
                        str(item).strip().lower()
                        for item in raw_list
                        if str(item).strip()
                    ]
                )
            return user_clean.lower() in acceptable if acceptable else False
        if question_type == "coding":
            return False
        return user_clean.lower() == answer_text.strip().lower()

    def _collect_question_tags(self, question: Dict[str, Any]) -> List[str]:
        tags: List[str] = []
        raw_tags = question.get("tags")
        if isinstance(raw_tags, list):
            tags.extend(str(tag) for tag in raw_tags)
        elif isinstance(raw_tags, str):
            tags.append(raw_tags)

        topic = question.get("topic")
        if isinstance(topic, list):
            tags.extend(str(tag) for tag in topic)
        elif isinstance(topic, str):
            tags.append(topic)

        return tags

    def _filter_allowed_tags(
        self, tags: List[str], allowed_lookup: Dict[str, str]
    ) -> List[str]:
        if not tags:
            return []
        if not allowed_lookup:
            return self._normalize_tags(tags)
        filtered: List[str] = []
        seen = set()
        for tag in tags:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key not in allowed_lookup or key in seen:
                continue
            seen.add(key)
            filtered.append(allowed_lookup[key])
        return filtered

    def _normalize_tags(self, tags: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for tag in tags or []:
            if not isinstance(tag, str):
                continue
            cleaned = tag.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
        return normalized

    def _extract_json_object(self, response_text: str) -> Optional[Dict[str, Any]]:
        if not response_text:
            return None
        stripped = response_text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", stripped)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None

    def _create_analysis_prompt(
        self,
        questions: List[Dict],
        answers: List[str],
        subject: str,
        subtopic: str,
        score: float,
        weak_areas: List[str],
    ) -> str:
        """Create a prompt for AI analysis of quiz performance."""
        prompt = f"""
Analyze a student's quiz performance for {subject} - {subtopic}.

Quiz Results:
- Score: {score:.1f}% ({len([a for a, q in zip(answers, questions) if a.lower().strip() == q.get('correct_answer', '').lower().strip()])} out of {len(questions)} correct)
- Weak areas: {', '.join(weak_areas) if weak_areas else 'None identified'}

Questions and Answers:
"""

        for i, (question, answer) in enumerate(zip(questions, answers)):
            correct = question.get("correct_answer", "")
            is_correct = answer.lower().strip() == correct.lower().strip()

            prompt += f"""
Q{i+1}: {question.get('question', '')}
Student Answer: {answer}
Correct Answer: {correct}
Result: {'+' if is_correct else '-'}

"""

        prompt += """
Provide a brief, encouraging analysis focusing on:
1. Strengths demonstrated
2. Specific areas for improvement
3. Study suggestions
4. Next steps for learning

Keep the response concise and student-friendly.
"""

        return prompt

    def _generate_recommendations(
        self, score: float, weak_areas: List[str], subject: str, subtopic: str
    ) -> List[str]:
        """Generate learning recommendations based on performance."""
        recommendations = []

        if score >= 80:
            recommendations.append(
                "Great job! You have a strong understanding of this topic."
            )
            recommendations.append("Consider advancing to more challenging topics.")
        elif score >= 60:
            recommendations.append(
                "Good progress! Focus on reviewing the areas you missed."
            )
            if weak_areas:
                recommendations.append(
                    f"Pay special attention to: {', '.join(weak_areas)}"
                )
        else:
            recommendations.append(
                "Consider reviewing the lesson materials before retaking the quiz."
            )
            recommendations.append(
                "Practice exercises might help strengthen your understanding."
            )
            if weak_areas:
                recommendations.append(f"Focus your study on: {', '.join(weak_areas)}")

        return recommendations

    def _get_fallback_analysis(
        self, questions: List[Dict], answers: List[str]
    ) -> Dict[str, Any]:
        """Provide fallback analysis when AI is not available."""
        total_questions = len(questions)
        normalized_answers = [
            str(answer) if answer is not None else "" for answer in answers
        ]
        correct_answers = 0
        for idx, question in enumerate(questions):
            user_answer = (
                normalized_answers[idx] if idx < len(normalized_answers) else ""
            )
            if self._is_answer_correct(question, user_answer):
                correct_answers += 1

        score_percentage = (
            (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        )

        return {
            "score": {
                "correct": correct_answers,
                "total": total_questions,
                "percentage": score_percentage,
            },
            "weak_areas": [],
            "weak_topics": [],
            "weak_tags": [],
            "ai_analysis": "AI analysis not available. Please review your answers and try again.",
            "feedback": "AI analysis not available. Please review your answers and try again.",
            "recommendations": self._generate_recommendations(
                score_percentage, [], "", ""
            ),
        }

    # ============================================================================
    # VIDEO RECOMMENDATIONS
    # ============================================================================

    def recommend_videos(
        self,
        subject: str,
        subtopic: str,
        weak_areas: List[str],
        available_videos: List[Dict],
    ) -> List[Dict]:
        """Recommend videos based on weak areas and available content."""
        if not available_videos:
            return []

        if not weak_areas:
            # If no weak areas, recommend all videos
            return available_videos

        # Simple keyword matching for video recommendations
        recommended = []

        for video in available_videos:
            video_title = video.get("title", "").lower()
            video_description = video.get("description", "").lower()
            video_tags = [tag.lower() for tag in video.get("tags", [])]

            # Check if video content matches weak areas
            for weak_area in weak_areas:
                weak_area_lower = weak_area.lower()

                if (
                    weak_area_lower in video_title
                    or weak_area_lower in video_description
                    or any(weak_area_lower in tag for tag in video_tags)
                ):

                    if video not in recommended:
                        recommended.append(video)
                    break

        return (
            recommended if recommended else available_videos[:3]
        )  # Fallback to first 3 videos

    # ============================================================================
    # REMEDIAL QUIZ GENERATION
    # ============================================================================

    def generate_remedial_quiz(
        self,
        original_questions: List[Dict],
        wrong_answers: List[int],
        question_pool: List[Dict],
        weak_topics: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Generate a remedial quiz focusing on areas where student struggled.

        Extracts tags from incorrect questions (and optional weak topics) to
        select the most relevant remedial questions from the pool.
        """
        if not question_pool:
            return []

        target_topics = set()
        for wrong_index in wrong_answers or []:
            if wrong_index < len(original_questions):
                question = original_questions[wrong_index]

                # Extract from tags field (list) - primary method
                tags = question.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        if tag and isinstance(tag, str):
                            target_topics.add(tag.strip().lower())
                elif isinstance(tags, str) and tags.strip():
                    # Single tag as string
                    target_topics.add(tags.strip().lower())

                # Fallback to legacy 'topic' field if it exists
                topic = question.get("topic", "")
                if topic and isinstance(topic, str):
                    target_topics.add(topic.strip().lower())

        for topic in weak_topics or []:
            if not isinstance(topic, str):
                continue
            cleaned = topic.strip().lower()
            if cleaned:
                target_topics.add(cleaned)

        if not target_topics:
            print("DEBUG: generate_remedial_quiz found no target topics")
            return []

        print(
            f"DEBUG: generate_remedial_quiz extracted target_topics: {target_topics}"
        )
        return self.select_remedial_questions(question_pool, list(target_topics))

    def select_remedial_questions(
        self,
        question_pool: Optional[Iterable[Dict]],
        target_tags: Optional[Iterable[str]] = None,
        min_questions: int = 7,
        max_questions: int = 10,
    ) -> List[Dict]:
        """Select a balanced set of remedial questions using AI.

        Uses OpenAI to intelligently select questions based on the student's
        weak topics, ensuring the most relevant questions are chosen.

        REQUIRES AI to be available - will return empty list if AI service is not configured.
        """

        print(f"DEBUG: select_remedial_questions called")
        print(f"DEBUG: question_pool type: {type(question_pool)}")
        print(f"DEBUG: target_tags: {target_tags}")

        if not question_pool:
            print(f"DEBUG: question_pool is empty, returning []")
            return []

        # Convert to list to work with it
        questions_list = (
            list(question_pool)
            if not isinstance(question_pool, list)
            else question_pool
        )

        if not questions_list:
            print(f"DEBUG: questions_list is empty after conversion")
            return []

        if not target_tags:
            print(
                f"ERROR: No target tags provided. Cannot select questions without weak topics."
            )
            self._last_selection_feedback = None
            return []

        if not self.is_available():
            print(
                "WARNING: AI service not available. Falling back to tag-based selection."
            )
            self._last_selection_feedback = None
            return self._tag_based_selection(
                questions_list, list(target_tags), min_questions, max_questions
            )

        print(f"DEBUG: Using AI for question selection")
        try:
            selected = self._ai_select_questions(
                questions_list, target_tags, min_questions, max_questions
            )
            if selected:
                print(f"DEBUG: AI selected {len(selected)} questions")
                return selected
            print("ERROR: AI selection returned empty list")
        except Exception as e:
            print(f"ERROR: AI selection failed with error: {e}")
        self._last_selection_feedback = None
        return self._tag_based_selection(
            questions_list, list(target_tags), min_questions, max_questions
        )

    def _ai_select_questions(
        self,
        questions: List[Dict],
        weak_topics: List[str],
        min_questions: int,
        max_questions: int,
    ) -> List[Dict]:
        """Use AI to select the most appropriate remedial questions."""

        # Prepare question summaries for AI
        question_summaries = []
        for i, q in enumerate(questions):
            summary = {
                "index": i,
                "question": q.get("question", "")[:200],  # Truncate long questions
                "type": q.get("type", "unknown"),
                "tags": q.get("tags", []),
            }
            question_summaries.append(summary)

        prompt = f"""You are an educational AI helping to create a remedial quiz for a student.

The student has shown weakness in these topics: {', '.join(weak_topics)}

Here are the available questions from the question pool:

{json.dumps(question_summaries, indent=2)}

Please analyze the questions and select {min_questions} to {max_questions} questions that would be most beneficial for this student's remedial learning.

Your selection should:
1. Focus primarily on the weak topics identified
2. Include a good mix of question types if available
3. Progress from foundational to more complex concepts
4. Ensure comprehensive coverage of the weak areas

Respond with a JSON object containing:
- "selected_indices": array of question indices to use (e.g., [0, 3, 7, 12])
- "reasoning": brief explanation of why these questions were selected
- "feedback": encouraging message for the student explaining what they'll be working on

Example response:
{{
  "selected_indices": [0, 2, 5, 7, 9, 11, 14],
  "reasoning": "Selected questions focusing on loops and conditionals with increasing complexity",
  "feedback": "These questions will help reinforce your understanding of loops and conditional statements, starting with basic concepts and building up to more complex scenarios."
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert educational assistant specializing in adaptive learning and question selection.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1000,
            )

            content = response.choices[0].message.content.strip()

            # Parse AI response
            if content.startswith("```json"):
                content = content.split("```json")[1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            selected_indices = result.get("selected_indices", [])

            # Store feedback for later display
            self._last_selection_feedback = {
                "reasoning": result.get("reasoning", ""),
                "feedback": result.get("feedback", ""),
            }

            # Return selected questions
            selected_questions = [
                questions[i] for i in selected_indices if 0 <= i < len(questions)
            ]

            # If AI didn't select enough questions, add some more
            if len(selected_questions) < min_questions:
                remaining = [
                    q for i, q in enumerate(questions) if i not in selected_indices
                ]
                random.shuffle(remaining)
                selected_questions.extend(
                    remaining[: min_questions - len(selected_questions)]
                )

            return selected_questions[:max_questions]

        except Exception as e:
            print(f"Error in AI question selection: {e}")
            return []

    def _tag_based_selection(
        self,
        questions: List[Dict],
        target_tags: Optional[List[str]],
        min_questions: int,
        max_questions: int,
    ) -> List[Dict]:
        """Fallback tag-based question selection."""

        normalized_targets: Set[str] = set()
        if target_tags:
            for tag in target_tags:
                if not isinstance(tag, str):
                    continue
                cleaned = tag.strip().lower()
                if cleaned:
                    normalized_targets.add(cleaned)

        prioritized: List[Dict] = []
        fallback: List[Dict] = []
        seen_identifiers: Set[str] = set()

        for question in questions:
            if not isinstance(question, dict):
                continue

            identifier = question.get("id") or question.get("question")
            if identifier is None:
                try:
                    identifier = json.dumps(question, sort_keys=True)
                except TypeError:
                    identifier = str(id(question))
            key = str(identifier).strip().lower()
            if key in seen_identifiers:
                continue
            seen_identifiers.add(key)

            tags: Set[str] = set()
            raw_tags = question.get("tags", [])
            if isinstance(raw_tags, (list, tuple, set)):
                for tag in raw_tags:
                    if isinstance(tag, str):
                        cleaned_tag = tag.strip().lower()
                        if cleaned_tag:
                            tags.add(cleaned_tag)
            elif isinstance(raw_tags, str):
                cleaned_tag = raw_tags.strip().lower()
                if cleaned_tag:
                    tags.add(cleaned_tag)

            matched = bool(normalized_targets and tags.intersection(normalized_targets))
            (prioritized if matched else fallback).append(question)

        random.shuffle(prioritized)
        random.shuffle(fallback)

        ordered_questions = prioritized + fallback
        if not ordered_questions:
            return []

        total_available = len(ordered_questions)
        upper_bound = min(max_questions, total_available)
        lower_bound = min(min_questions, upper_bound) if upper_bound else 0

        if lower_bound == 0:
            return ordered_questions

        if lower_bound == upper_bound:
            target_count = upper_bound
        else:
            target_count = random.randint(lower_bound, upper_bound)

        result = ordered_questions[:target_count]
        print(f"DEBUG: Tag-based selection returning {len(result)} questions")
        return result

    def get_last_selection_feedback(self) -> Optional[Dict[str, str]]:
        """Get feedback from the last AI question selection."""
        return getattr(self, "_last_selection_feedback", None)

    # ============================================================================
    # CONTENT GENERATION HELPERS
    # ============================================================================

    def generate_lesson_suggestions(
        self, subject: str, subtopic: str, current_lessons: List[Dict]
    ) -> Optional[str]:
        """Generate suggestions for new lesson content."""
        if not self.is_available():
            return None

        prompt = f"""
Analyze the existing lessons for {subject} - {subtopic} and suggest improvements or additional content.

Existing Lessons:
"""

        for i, lesson in enumerate(
            current_lessons[:5]
        ):  # Limit to first 5 for prompt size
            prompt += f"{i+1}. {lesson.get('title', 'Untitled')}\n"

        prompt += """
Provide 3-5 specific suggestions for:
1. New lesson topics that would complement existing content
2. Improvements to existing lessons
3. Interactive exercises that could be added

Keep suggestions practical and educational.
"""

        return self.call_openai_api(prompt)

    def validate_question_quality(self, question_data: Dict) -> Dict[str, Any]:
        """Validate and provide feedback on question quality."""
        if not self.is_available():
            return {"valid": True, "suggestions": []}

        prompt = f"""
Evaluate this quiz question for quality, clarity, and educational value:

Question: {question_data.get('question', '')}
Options: {', '.join(question_data.get('options', []))}
Correct Answer: {question_data.get('correct_answer', '')}
Explanation: {question_data.get('explanation', 'None provided')}

Provide feedback on:
1. Question clarity
2. Answer options quality
3. Difficulty appropriateness
4. Suggestions for improvement

Respond with a brief assessment and specific recommendations.
"""

        feedback = self.call_openai_api(prompt)

        return {
            "valid": True,  # Assume valid unless obvious issues
            "feedback": feedback,
            "suggestions": [],  # Could be parsed from feedback if needed
        }
