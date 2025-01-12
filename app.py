import json
import os
import logging

from flask import Flask, render_template, request, redirect, url_for, flash
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.trace import SpanKind
from pythonjsonlogger import jsonlogger


# Set up JSON logging
log_handler = logging.FileHandler("app.log")
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
)
log_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[log_handler]
)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'secret'
COURSE_FILE = 'course_catalog.json'
tracer = trace.get_tracer(__name__)
FlaskInstrumentor().instrument_app(app)

jaeger_host = os.getenv("JAEGER_HOST", "localhost")
jaeger_port = int(os.getenv("JAEGER_PORT", 6831))

trace.set_tracer_provider(
    TracerProvider(resource=Resource.create({"service.name": "course-catalog-service"}))
)

jaeger_exporter = JaegerExporter(
    agent_host_name=jaeger_host,
    agent_port=jaeger_port
)

trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)


def load_courses():
    """Load courses from the JSON file."""
    if not os.path.exists(COURSE_FILE):
        return [] 
    with open(COURSE_FILE, 'r') as file:
        return json.load(file)


def save_courses(data):
    """Save new course data to the JSON file."""
    courses = load_courses()
    courses.append(data) 
    with open(COURSE_FILE, 'w') as file:
        json.dump(courses, file, indent=4)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/catalog')
def course_catalog():
    with tracer.start_as_current_span("Render Course Catalog") as span:
        span.set_attribute("route", "/catalog")
        span.set_attribute("method", request.method)
        span.set_attribute("user.ip", request.remote_addr)  

        courses = load_courses()
        logging.info("Loaded course catalog", extra={"total_courses": len(courses)})
        return render_template('course_catalog.html', courses=courses)


@app.route('/course/<code>')
def course_details(code):
    with tracer.start_as_current_span("View Course Details") as span:
        courses = load_courses()
        course = next((course for course in courses if course['code'] == code), None)
        if not course:
            logger.error("Course not found", extra={"code": code})
            flash(f"No course found with code '{code}'.", "error")
            return redirect(url_for('course_catalog'))
        return render_template('course_details.html', course=course)


@app.route('/add_course', methods=['GET', 'POST'])
def add_courses():
    if request.method == 'POST':
        course = {
            'code': request.form['code'],
            'name': request.form['name'],
            'instructor': request.form['instructor'],
            'semester': request.form['semester'],
            'schedule': request.form['schedule'],
            'classroom': request.form['classroom'],
            'prerequisites': request.form['prerequisites'],
            'grading': request.form['grading'],
            'description': request.form['description']
        }
        missing = [key for key, value in course.items() if not value]
        if missing:
            logger.error("Validation failed", extra={"missing_fields": missing})
            flash(f"Please fill in all the required fields: {missing}", "error")
            return render_template('add_courses.html', course=course)

        save_courses(course)
        logger.info("Course added successfully", extra={"course_code": course["code"]})
        flash(f"Course '{course['name']}' added successfully!", "success")
        return redirect(url_for('course_catalog'))

    return render_template('add_courses.html')


if __name__ == '__main__':
    app.run(debug=True)
    