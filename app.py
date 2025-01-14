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
console_logs = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s %(pathname)s %(lineno)d'
)
log_handler.setFormatter(formatter)
console_logs.setFormatter(formatter)

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[log_handler,console_logs]
)

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)
total_errors=0
total_catalogs = 0


app = Flask(__name__)
app.secret_key = 'secret'

COURSE_FILE = 'course_catalog.json'

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
    global total_catalogs
    with tracer.start_as_current_span("Render Course Catalog") as span:
        span.set_attribute("route", "/catalog")
        span.set_attribute("method", request.method)
        span.set_attribute("user.ip", request.remote_addr)  

        with tracer.start_as_current_span("Load Courses from JSON") as load_span:
            courses = load_courses()
            load_span.set_attribute("total_courses", len(courses))  
            if courses:
                load_span.set_attribute("course_codes", [course['code'] for course in courses])  
            else:
                load_span.set_attribute("is_empty_catalog", True) 

        with tracer.start_as_current_span("Render HTML Page") as render_span:
            render_span.set_attribute("template", "course_catalog.html")
            render_span.set_attribute("total_courses_rendered", len(courses))
            total_catalogs+=1
            render_span.set_attribute("Total Times Course Catalog Page visited", total_catalogs)
            return render_template('course_catalog.html', courses=courses)


@app.route('/course/<code>')
def course_details(code):
    with tracer.start_as_current_span("View Course Details") as span:
        span.set_attribute("route", f"/course/{code}")
        span.set_attribute("method", request.method)
        span.set_attribute("user.ip", request.remote_addr) 
        span.set_attribute("course_code", code)
        
        with tracer.start_as_current_span("Load Courses from JSON") as load_span:
            courses = load_courses()
            load_span.set_attribute("total_courses", len(courses))
        
        with tracer.start_as_current_span("Find Course by Code") as find_span:
            course = next((course for course in courses if course['code'] == code), None)
            find_span.set_attribute("course_found", bool(course))
            
        if not course:
            span.set_status(trace.status.Status(trace.status.StatusCode.ERROR, f"No course found for code {code}"))
            flash(f"No course found with code '{code}'.", "error")
            return redirect(url_for('course_catalog'))
        
        with tracer.start_as_current_span("Render Course Details Page") as render_span:
            render_span.set_attribute("template", "course_details.html")
            return render_template('course_details.html', course=course)


@app.route('/add_course', methods=['GET', 'POST'])
def add_courses():
    
    global total_errors
    
    with tracer.start_as_current_span("Add Course Operation") as span:
        span.set_attribute("route", "/add_course")
        span.set_attribute("method", request.method)
        span.set_attribute("user.ip", request.remote_addr) 

        if request.method == 'POST':
            with tracer.start_as_current_span("Process Form Submission") as form_span:
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
                form_span.set_attribute("course.code", course['code'])
                form_span.set_attribute("course.name", course['name'])
                form_span.set_attribute("course.instructor", course['instructor'])
            
                missing = []
                if course["code"] == "": missing.append('code')
                if course["name"] == "": missing.append('name')
                if course["instructor"] == "": missing.append('instructor')
                
                form_span.set_attribute("missing_fields", missing)
               
                
                if len(missing) != 0:
                    flash(f'''
                            Please fill in all the required fields,
                            missing fields: {missing}
                        ''', "error")
                    total_errors +=1
                    form_span.set_attribute("Error Count",total_errors)
                    logging.error(f"Missing fields: {missing}")
                    return render_template('add_courses.html', course=course)
                
                with tracer.start_as_current_span("Save Course Data") as save_span:
                    save_courses(course)
                    save_span.set_attribute("is_course_saved", True)
                    save_span.set_attribute("total_courses", len(load_courses()))  
                    logging.info(f"Course '{course['name']}' with code '{course['code']}' added to the catalog.")
                
                flash(f"Course '{course['name']}' added successfully!", "success")
                return redirect(url_for('course_catalog'))
        
        with tracer.start_as_current_span("Render Add Course Page") as render_span:
            render_span.set_attribute("template", "add_courses.html")
            return render_template('add_courses.html')


if __name__ == '__main__':
    app.run(debug=True)

