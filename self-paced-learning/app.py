"""
Flask Application with Refactored Architecture

This is the main Flask application file that integrates:
- Service layer for business logic
- Blueprint system for organized routes
- Maintained backward com    print("\n[*] Starting Flask application with refactored architecture...")atibility

This new version runs alongside the original app.py for safe testing.
"""

import os
import json
import re
from datetime import datetime
from flask import Flask, session, render_template, jsonify
from dotenv import load_dotenv
import werkzeug

from extensions import db, migrate, cache
from models import (  # noqa: F401
    AnonUser,
    Attempt,
    Class,
    ClassRegistration,
    Cycle,
    LessonProgress,
    User,
)

# Import our refactored services and blueprints
from services import init_services
from blueprints import register_blueprints, get_blueprint_info

# Load environment variables
load_dotenv()

if not getattr(werkzeug, '__version__', None):
    werkzeug.__version__ = '3'

# Create Flask application
app = Flask(__name__)

# Database configuration
def _normalize_sqlite_uri(uri: str, base_dir: str) -> str:
    if not uri or not uri.startswith("sqlite:///"):
        return uri
    raw_path = uri.replace("sqlite:///", "", 1)
    # If already absolute (drive letter or leading slash), leave as-is.
    if os.path.isabs(raw_path) or re.match(r"^[A-Za-z]:[\\/]", raw_path):
        return uri
    abs_path = os.path.abspath(os.path.join(base_dir, raw_path))
    return f"sqlite:///{abs_path.replace(os.sep, '/')}"


default_db_path = os.path.join(app.instance_path, "self_paced_learning.db")
os.makedirs(app.instance_path, exist_ok=True)
raw_db_uri = os.getenv("DATABASE_URL", f"sqlite:///{default_db_path.replace(os.sep, '/')}")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_sqlite_uri(raw_db_uri, app.root_path)
app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
app.config.setdefault("TEMPLATES_AUTO_RELOAD", True)

# Initialize extensions
db.init_app(app)
migrate.init_app(app, db)

# App configuration
app.secret_key = os.getenv("FLASK_KEY")
if not app.secret_key:
    app.logger.warning(
        "FLASK_KEY not set, using a default secret key. Please set this in your .env file for production."
    )
    app.secret_key = "your_default_secret_key_for_development_12345_v2"

app.config.setdefault("CACHE_TYPE", os.getenv("CACHE_TYPE", "SimpleCache"))
app.config.setdefault("CACHE_DEFAULT_TIMEOUT", int(os.getenv("CACHE_TTL", "60")))
cache.init_app(app)

# Initialize data path
DATA_ROOT_PATH = os.path.join(os.path.dirname(__file__), "data")

# Initialize services with data path
print("[*] Initializing services...")
init_services(DATA_ROOT_PATH)
print("[+] Services initialized successfully")

# Register all blueprints
print("[*] Registering blueprints...")
register_blueprints(app)
print("[+] Blueprints registered successfully")

# Display blueprint information
blueprint_info = get_blueprint_info()
print("\\n[*] Blueprint Configuration:")
for name, info in blueprint_info.items():
    print(f"   {name}: {info['url_prefix']} - {info['description']}")


# Legacy helper functions for backward compatibility
def extract_video_id_from_url(url: str) -> str:
    """Extract YouTube video ID from various YouTube URL formats."""
    if not url:
        return ""

    # Handle different YouTube URL formats
    patterns = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\\?v=([^&\\n?#]+)",
        r"(?:https?://)?(?:www\.)?youtube\.com/embed/([^&\\n?#]+)",
        r"(?:https?://)?(?:www\.)?youtu\.be/([^&\\n?#]+)",
        r"(?:https?://)?(?:www\.)?youtube\.com/v/([^&\\n?#]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return ""


def call_openai_api(prompt: str, model: str = "gpt-4") -> str:
    """Legacy OpenAI API wrapper - now delegates to AIService."""
    from services import get_ai_service

    ai_service = get_ai_service()
    return ai_service.call_openai_api(prompt, model)


# Application startup validation
def validate_setup():
    """Validate application setup on first request."""
    from services import get_data_service

    try:
        data_service = get_data_service()

        # Validate that we have the required data structure
        if not data_service.validate_subject_subtopic("python", "functions"):
            app.logger.warning(
                "Python functions data not found. Check data/subjects/python/functions/ directory."
            )

        # Check OpenAI API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            app.logger.warning(
                "OPENAI_API_KEY environment variable not set. AI features will not work."
            )

        app.logger.info("Application validation completed successfully")

    except Exception as e:
        app.logger.error(f"Application validation failed: {e}")


# Run validation on startup
validate_setup()


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    try:
        return render_template("404.html"), 404
    except:
        return "<h1>404 - Page Not Found</h1><p><a href='/'>Return to Home</a></p>", 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    try:
        return render_template("500.html"), 500
    except:
        return (
            "<h1>500 - Internal Server Error</h1><p><a href='/'>Return to Home</a></p>",
            500,
        )


# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint for monitoring."""
    from services import get_service_factory

    try:
        factory = get_service_factory()
        services = factory.get_all_services()

        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {
                "data_service": "available",
                "progress_service": "available",
                "ai_service": (
                    "available" if services["ai_service"].is_available() else "limited"
                ),
                "admin_service": "available",
            },
            "blueprint_info": get_blueprint_info(),
        }

        return jsonify(health_status)

    except Exception as e:
        return (
            jsonify(
                {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            500,
        )


# Development route for testing service integration
@app.route("/dev/test-services")
def test_services():
    """Development endpoint to test service integration."""
    from services import (
        get_data_service,
        get_progress_service,
        get_ai_service,
        get_admin_service,
    )

    try:
        diagnostics_allowed = app.debug or app.testing
        environment_notice = (
            "<p><em>Diagnostics limited outside debug/test mode.</em></p>"
            if not diagnostics_allowed
            else ""
        )

        # Test each service
        results = {
            "data_service": "[FAILED]",
            "progress_service": "[FAILED]",
            "ai_service": "[FAILED]",
            "admin_service": "[FAILED]",
        }

        # Test data service
        data_service = get_data_service()
        subjects = data_service.discover_subjects()
        if subjects:
            results["data_service"] = f"[OK] Found {len(subjects)} subjects"

        # Test progress service
        progress_service = get_progress_service()
        test_key = progress_service.get_session_key("python", "functions", "test")
        if test_key == "python_functions_test":
            results["progress_service"] = "[OK] Session keys working"

        # Test AI service
        ai_service = get_ai_service()
        if ai_service.is_available():
            results["ai_service"] = "[OK] OpenAI available"
        else:
            results["ai_service"] = "[WARNING] OpenAI not configured"

        # Test admin service
        admin_service = get_admin_service()
        dashboard = admin_service.get_dashboard_stats()
        if dashboard:
            results["admin_service"] = "[OK] Dashboard data available"

        return f"""
        <h2>Service Integration Test</h2>
        {environment_notice}
        <ul>
        {"".join([f"<li><strong>{service}:</strong> {status}</li>" for service, status in results.items()])}
        </ul>
        <p><a href="/"><-- Back to home</a></p>
        """

    except Exception as e:
        return (
            f"<h2>Service Test Failed</h2><p>Error: {e}</p><p><a href="
            / "><-- Back to home</a></p>"
        )


if __name__ == "__main__":
    # Additional startup logging
    print("\n[*] Starting Flask application with refactored architecture...")
    print(f"[DATA] Data root path: {DATA_ROOT_PATH}")
    print(f"[SECRET] Secret key configured: {'Yes' if app.secret_key else 'No'}")
    print(f"[AI] OpenAI configured: {'Yes' if os.getenv('OPENAI_API_KEY') else 'No'}")
    print("\\n" + "=" * 50)
    print("Application ready! [READY]")
    print("=" * 50)

    app.run(
        debug=True, port=5001
    )  # Use different port to avoid conflict with original app
