import json 
import logging 
import requests
import time 

from flask import request, Blueprint, abort
from CTFd.models import Users
from CTFd.utils.decorators import authed_only

from ..models import Dojos, DojoChallenges, DojoStudents, DojoStudents
from .course import grade
from ..utils.dojo import dojo_route

canvas = Blueprint("canvas", __name__)

log=logging.getLogger(__name__)

""" Endpoint to do a full class canvas sync """
@canvas.route("/dojo/<dojo>/admin/canvas_sync")
@dojo_route
@authed_only
def canvas_sync_all(dojo):
    if not dojo.course:
        abort(404)

    if not dojo.is_admin():
        abort(403)
    
    posting_results = do_canvas_sync(dojo)
        
    return json.dumps(posting_results, indent=2)


"""
This is called from the the DojoFlag class on a successful flag submission.
It updates a single user's Canvas grade for the module that the the user just sucessfully submitted 
"""
@authed_only
def sync_challenge_to_canvas(challenge_id, user_id):
    dojo_chal = DojoChallenges.query.filter(DojoChallenges.challenge_id == challenge_id).first()
    if dojo_chal:
        dojo = Dojos.query.filter(Dojos.dojo_id == dojo_chal.dojo_id).first()

        posting_results = do_canvas_sync(dojo, user_id=user_id, module_id=dojo_chal.module.id)
    
        log.info("Result from post", json.dumps(posting_results, indent=2))


""" 
This function will retrieve the grade information, format it, and send to canvas
However, if both user_id and module_id are supplied it will do a single user/module update 
"""
def do_canvas_sync(dojo, user_id=None, module_id=None):
    
    canvas_token = dojo.course.get("canvas_token","")
    
    canvas_api_host = dojo.course.get("canvas_api_host","")
    canvas_course_id = dojo.course.get("canvas_course_id",0)
    if len(canvas_token) == 0:
        return {"status": "completed", "message": "Missing canvas_token in course.xml"}
    if len(canvas_api_host) == 0:
        return {"status": "completed", "message": "Missing canvas_api_host in course.xml"}
    if canvas_course_id == 0:
        return {"status": "completed", "message": "Missing canvas_course_id in course.xml"}
    
    canvas_grade_data = {}
    
    ignore_pending = request.args.get("ignore_pending") is not None
        
    students = {student.user_id: student.token for student in dojo.students}
    course_students = dojo.course.get("students", [])
    missing_students = list(set(course_students) - set(students.values()))
    
    # if user_id is None, it's a bulk grade submission, get all users, else just get user_id
    if user_id is None: 
        users = (
                Users
                .query
                .join(DojoStudents, DojoStudents.user_id == Users.id)
                .filter(DojoStudents.dojo == dojo,
                        DojoStudents.token.in_(course_students))
            )
    else:
        # get the user_id
        users = (
                Users
                .query
                .join(DojoStudents, DojoStudents.user_id == Users.id)
                .filter(DojoStudents.dojo == dojo,
                        DojoStudents.token.in_(course_students),
                        DojoStudents.user_id == user_id)
            )
        if users.count() == 0:
            return {"status": "completed", "message": f"Student {user_id} has not linked their student id with this course"}

    grades = sorted(grade(dojo, users, ignore_pending=ignore_pending),
                        key=lambda grade: grade["overall_grade"],
                        reverse=True)
    assessments = dojo.course.get("assessments", [])
        
    posting_results = []
    progress_urls = []
    assessment_student_counter = {}
    for aindex, assessment in enumerate(assessments):
        if "canvas_assignment_id" not in assessment:
            continue
        assessment_student_counter[assessment['id']] = 0
        # if we have a value module_id, check for it and skip all the others
        if module_id is not None and module_id != assessment["id"]:                
            continue 
                    
        canvas_assignment_id = assessment["canvas_assignment_id"]
        for grade_res in grades:                
            grade_credit_percent = f"{grade_res['assessment_grades'][aindex]['credit'] * 100:.2f}%"

            # this is a single module sync, submit to canvas and return
            if module_id is not None and module_id == assessment["id"]:   
                
                res = post_grade_to_canvas(canvas_token, canvas_api_host, canvas_course_id, assessment["canvas_assignment_id"], 
                                        students[grade_res["user_id"]], grade_credit_percent)
                
                return res
            # multi-module and mutli-user sync of grades with canvas using bulk update api
            else:
                # additional check to be sure that they align 
                if grade_res['assessment_grades'][aindex]['module_id'] == assessment['id']:
                    student_id = students[grade_res['user_id']]
                    canvas_grade_data[f"sis_user_id:{student_id}"] = {"posted_grade": grade_credit_percent}
                    assessment_student_counter[assessment['id']] += 1
                else:
                    log.error(f"The following did not align in list, {grade_res['assessment_grades'][aindex]['module_id']=}   {assessment['id']=}" )
                    return {"status": "failed", "message": f"The following did not align in list, {grade_res['assessment_grades'][aindex]['module_id']=}   {assessment['id']=}, this shouldn't happen."}

        if (len(canvas_grade_data) > 0):
            submission_results = post_bulk_grade_data_to_canvas(canvas_token, canvas_api_host, canvas_course_id, canvas_assignment_id, canvas_grade_data)
            if submission_results["status"] == "success":
                progress_urls.append(submission_results["url"])
            else:
                posting_results.append(submission_results)            
        
    if len(progress_urls) > 0 :
        check_results = check_progress(progress_urls, canvas_token, interval=2)
        posting_results.extend(check_results)
        posting_results.append(assessment_student_counter)

    return posting_results


def post_grade_to_canvas(canvas_token, canvas_api_host, canvas_course_id, assignment_id, student_id, students_grade):
    url = f"https://{canvas_api_host}/api/v1/courses/{canvas_course_id}/assignments/{assignment_id}/submissions/sis_user_id:{student_id}"
    payload = {'submission': {'posted_grade': students_grade}}
    
    header = {'Authorization': 'Bearer ' + canvas_token}
    
    r = requests.put(url, headers=header, json=payload)
    
    if r.status_code == 200:
        return {"status": "success", "student_id": student_id, "json": r.json()}
    else:
        return {"student_id": student_id, "code": r.status_code, "text": r.text, "url": url, "canvas_token": canvas_token}
    

def post_bulk_grade_data_to_canvas(canvas_token, canvas_api_host, canvas_course_id, assignment_id, canvas_grade_data):
    url = f"https://{canvas_api_host}/api/v1/courses/{canvas_course_id}/assignments/{assignment_id}/submissions/update_grades"
    payload = {'grade_data': canvas_grade_data}
    
    header = {
                'Authorization': 'Bearer ' + canvas_token,
                "Content-Type": "application/json"
            }
    
    r = requests.post(url, headers=header, json=payload)
    
    r_json = r.json()
    
    if r.status_code == 200:
        r_json["status"] = "success"
        return r_json
    else:
        r_json.update({"status": "failed", "code": r.status_code, "text": r.text, "url": url})
        return  r_json
    
""" 
For bulk submissions we do not get an immediate result, but instead get a progress url 
This function checks the progress up to 20 times and reports back to user on completion or failure to complete
"""
def check_progress(progress_urls, access_token, interval=5):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    completed = []
    check_count = 0
    max_checks = 10
    most_recent = dict()
    while len(completed) < len(progress_urls):
        
        for url in progress_urls:
            if url not in completed:
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    progress_data = response.json()
                    if progress_data.get('workflow_state') == 'completed':
                        completed.append({"status": "success", "url": url, "completion": progress_data.get('completion',0)})                    
                    else:
                        most_recent[url] = {"status": "incomplete", "url": url, "completion": progress_data.get('completion',0)}
                else:
                    print(f"Failed to check progress for {url}. Status code: {response.status_code}")
                    completed.append({"status": "failed", "url": url,
                                   "status_code": response.status_code,
                                   "json": response.json()}) 
                                       
        
        check_count += 1
        if check_count == max_checks:
            for url in progress_urls:
                if url not in completed:
                    if url in most_recent:
                        completed.append(most_recent[url])
                    else:
                        completed.append({"status": "failed", "url": url, "message": "unable to get update"})

            break 
        time.sleep(interval)
    return completed 
