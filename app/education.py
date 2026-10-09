"""Private administrator-owned school pilot with descriptive progress summaries."""
import sqlite3,uuid
from datetime import date
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .db import connect,audit,now
SCHEMA='''
CREATE TABLE IF NOT EXISTS edu_schools(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES staff(id),name TEXT NOT NULL,target REAL NOT NULL CHECK(target BETWEEN 0 AND 100));
CREATE TABLE IF NOT EXISTS edu_students(id TEXT PRIMARY KEY,school_id TEXT NOT NULL REFERENCES edu_schools(id),code TEXT NOT NULL,name TEXT NOT NULL,class_name TEXT NOT NULL,UNIQUE(school_id,code));
CREATE TABLE IF NOT EXISTS edu_subjects(id TEXT PRIMARY KEY,school_id TEXT NOT NULL REFERENCES edu_schools(id),name TEXT NOT NULL,UNIQUE(school_id,name));
CREATE TABLE IF NOT EXISTS edu_assessments(id TEXT PRIMARY KEY,school_id TEXT NOT NULL REFERENCES edu_schools(id),subject_id TEXT NOT NULL REFERENCES edu_subjects(id),title TEXT NOT NULL,topic TEXT NOT NULL,class_name TEXT NOT NULL,assessed_on TEXT NOT NULL,max_score REAL NOT NULL CHECK(max_score>0),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS edu_results(assessment_id TEXT NOT NULL REFERENCES edu_assessments(id),student_id TEXT NOT NULL REFERENCES edu_students(id),score REAL NOT NULL CHECK(score>=0),updated_at TEXT NOT NULL,PRIMARY KEY(assessment_id,student_id));
CREATE INDEX IF NOT EXISTS edu_students_school ON edu_students(school_id);
CREATE INDEX IF NOT EXISTS edu_assessments_school ON edu_assessments(school_id);
'''
class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class School(Model):
    name:str=Field(min_length=1,max_length=160)
    target:Decimal=Field(default=Decimal('50'),ge=0,le=100,allow_inf_nan=False)
class Student(Model):
    code:str=Field(min_length=1,max_length=50)
    name:str=Field(min_length=1,max_length=160)
    class_name:str=Field(min_length=1,max_length=80)
class Subject(Model):name:str=Field(min_length=1,max_length=100)
class Assessment(Model):
    subject_id:str=Field(min_length=1,max_length=40)
    title:str=Field(min_length=1,max_length=160)
    topic:str=Field(default='',max_length=160)
    class_name:str=Field(min_length=1,max_length=80)
    assessed_on:date
    max_score:Decimal=Field(gt=0,le=100000,allow_inf_nan=False)
    @field_validator('assessed_on')
    @classmethod
    def past(cls,value):
        if value>date.today():raise ValueError('Date cannot be in the future')
        return value
class Result(Model):
    student_id:str=Field(min_length=1,max_length=40)
    score:Decimal|None=Field(default=None,ge=0,allow_inf_nan=False)
class Results(Model):items:list[Result]=Field(max_length=200)
def router(settings,staff):
    r=APIRouter(prefix='/api/admin/education')
    def school(db,sid,user):
        row=db.execute('SELECT * FROM edu_schools WHERE id=? AND owner_id=?',(sid,user['staff_id'])).fetchone()
        if not row:raise HTTPException(404,'School not found')
        return dict(row)
    def linked(db,table,identifier,sid):
        row=db.execute(f'SELECT * FROM {table} WHERE id=? AND school_id=?',(identifier,sid)).fetchone()
        if not row:raise HTTPException(404,'Record not found in this school')
        return dict(row)
    @r.get('/schools')
    def schools(user=Depends(staff)):
        with connect(settings.db_path) as db:return {'items':[dict(x) for x in db.execute('SELECT * FROM edu_schools WHERE owner_id=? ORDER BY name',(user['staff_id'],))]}
    @r.post('/schools',status_code=201)
    def add_school(data:School,user=Depends(staff)):
        sid=uuid.uuid4().hex
        with connect(settings.db_path) as db:
            db.execute('INSERT INTO edu_schools VALUES(?,?,?,?)',(sid,user['staff_id'],data.name,float(data.target)));audit(db,user['staff_id'],'education_create_school',sid);return school(db,sid,user)
    @r.put('/schools/{sid}')
    def edit_school(sid:str,data:School,user=Depends(staff)):
        with connect(settings.db_path) as db:
            school(db,sid,user);db.execute('UPDATE edu_schools SET name=?,target=? WHERE id=?',(data.name,float(data.target),sid));audit(db,user['staff_id'],'education_update_school',sid);return school(db,sid,user)
    @r.get('/schools/{sid}/workspace')
    def workspace(sid:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            result={'school':school(db,sid,user)}
            for kind in ['students','subjects','assessments']:result[kind]=[dict(x) for x in db.execute(f'SELECT * FROM edu_{kind} WHERE school_id=? ORDER BY '+('assessed_on,created_at,id' if kind=='assessments' else 'name'),(sid,))]
            audit(db,user['staff_id'],'education_view_school',sid);return result
    @r.post('/schools/{sid}/students',status_code=201)
    def add_student(sid:str,data:Student,user=Depends(staff)):
        identifier=uuid.uuid4().hex
        with connect(settings.db_path) as db:
            school(db,sid,user)
            try:db.execute('INSERT INTO edu_students VALUES(?,?,?,?,?)',(identifier,sid,data.code,data.name,data.class_name))
            except sqlite3.IntegrityError:raise HTTPException(409,'Student code already exists')
            audit(db,user['staff_id'],'education_create_student',identifier);return linked(db,'edu_students',identifier,sid)
    @r.put('/schools/{sid}/students/{identifier}')
    def edit_student(sid:str,identifier:str,data:Student,user=Depends(staff)):
        with connect(settings.db_path) as db:
            school(db,sid,user);old=linked(db,'edu_students',identifier,sid)
            if old['class_name']!=data.class_name and db.execute('SELECT 1 FROM edu_results WHERE student_id=? LIMIT 1',(identifier,)).fetchone():raise HTTPException(409,'Class transfers with existing results are not supported in this pilot')
            try:db.execute('UPDATE edu_students SET code=?,name=?,class_name=? WHERE id=?',(data.code,data.name,data.class_name,identifier))
            except sqlite3.IntegrityError:raise HTTPException(409,'Student code already exists')
            audit(db,user['staff_id'],'education_update_student',identifier);return linked(db,'edu_students',identifier,sid)
    @r.delete('/schools/{sid}/students/{identifier}')
    def delete_student(sid:str,identifier:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            school(db,sid,user);linked(db,'edu_students',identifier,sid)
            if db.execute('SELECT 1 FROM edu_results WHERE student_id=? LIMIT 1',(identifier,)).fetchone():raise HTTPException(409,'Student has results and cannot be removed in this pilot')
            db.execute('DELETE FROM edu_students WHERE id=?',(identifier,));audit(db,user['staff_id'],'education_delete_student',identifier);return {'ok':True}
    @r.post('/schools/{sid}/subjects',status_code=201)
    def add_subject(sid:str,data:Subject,user=Depends(staff)):
        identifier=uuid.uuid4().hex
        with connect(settings.db_path) as db:
            school(db,sid,user)
            try:db.execute('INSERT INTO edu_subjects VALUES(?,?,?)',(identifier,sid,data.name))
            except sqlite3.IntegrityError:raise HTTPException(409,'Subject already exists')
            audit(db,user['staff_id'],'education_create_subject',identifier);return linked(db,'edu_subjects',identifier,sid)
    @r.post('/schools/{sid}/assessments',status_code=201)
    def add_assessment(sid:str,data:Assessment,user=Depends(staff)):
        identifier=uuid.uuid4().hex
        with connect(settings.db_path) as db:
            school(db,sid,user);linked(db,'edu_subjects',data.subject_id,sid)
            db.execute('INSERT INTO edu_assessments VALUES(?,?,?,?,?,?,?,?,?)',(identifier,sid,data.subject_id,data.title,data.topic,data.class_name,data.assessed_on.isoformat(),float(data.max_score),now()));audit(db,user['staff_id'],'education_create_assessment',identifier);return linked(db,'edu_assessments',identifier,sid)
    @r.get('/schools/{sid}/assessments/{identifier}/results')
    def results(sid:str,identifier:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            school(db,sid,user);a=linked(db,'edu_assessments',identifier,sid)
            return {'assessment':a,'items':[dict(x) for x in db.execute('SELECT s.id,s.code,s.name,r.score FROM edu_students s LEFT JOIN edu_results r ON r.student_id=s.id AND r.assessment_id=? WHERE s.school_id=? AND s.class_name=? ORDER BY s.name',(identifier,sid,a['class_name']))]}
    @r.put('/schools/{sid}/assessments/{identifier}/results')
    def save_results(sid:str,identifier:str,data:Results,user=Depends(staff)):
        with connect(settings.db_path) as db:
            db.execute('BEGIN IMMEDIATE');school(db,sid,user);a=linked(db,'edu_assessments',identifier,sid);seen=set()
            for item in data.items:
                st=linked(db,'edu_students',item.student_id,sid)
                if item.student_id in seen:raise HTTPException(422,'Duplicate student in result list')
                seen.add(item.student_id)
                if st['class_name']!=a['class_name']:raise HTTPException(422,'Student is not in this assessment class')
                if item.score is not None and item.score>Decimal(str(a['max_score'])):raise HTTPException(422,'Score exceeds the assessment maximum')
            for item in data.items:
                if item.score is None:db.execute('DELETE FROM edu_results WHERE assessment_id=? AND student_id=?',(identifier,item.student_id))
                else:db.execute('INSERT INTO edu_results VALUES(?,?,?,?) ON CONFLICT(assessment_id,student_id) DO UPDATE SET score=excluded.score,updated_at=excluded.updated_at',(identifier,item.student_id,float(item.score),now()))
            audit(db,user['staff_id'],'education_save_results',identifier);return {'saved':len(data.items)}
    @r.get('/schools/{sid}/progress')
    def progress(sid:str,user=Depends(staff)):
        with connect(settings.db_path) as db:
            info=school(db,sid,user);students=[dict(x) for x in db.execute('SELECT * FROM edu_students WHERE school_id=? ORDER BY class_name,name',(sid,))]
            rows=[dict(x) for x in db.execute('SELECT r.student_id,r.score,a.subject_id,a.title,a.topic,a.max_score,a.assessed_on,s.name subject FROM edu_results r JOIN edu_assessments a ON a.id=r.assessment_id JOIN edu_subjects s ON s.id=a.subject_id WHERE a.school_id=? ORDER BY a.assessed_on,a.created_at,a.id',(sid,))]
            histories={}
            for row in rows:histories.setdefault(row['student_id'],{}).setdefault(row['subject_id'],[]).append(row)
            for student in students:
                student['subjects']=[]
                for items in histories.get(student['id'],{}).values():
                    last=items[-1];pct=last['score']/last['max_score']*100;prior=items[-2] if len(items)>1 else None;delta=pct-prior['score']/prior['max_score']*100 if prior else None
                    student['subjects'].append({'subject':last['subject'],'latest_percent':round(pct,2),'change_points':round(delta,2) if delta is not None else None,'assessment_count':len(items),'latest_title':last['title'],'assessed_on':last['assessed_on'],'topic':last['topic'],'focus':pct<info['target'],'suggestion':('Review '+(last['topic'] or last['subject'])+' with the teacher; agree focused practice and reassess.' if pct<info['target'] else 'Continue practice and review the next assessment.')})
                student['latest_subject_average']=round(sum(x['latest_percent'] for x in student['subjects'])/len(student['subjects']),2) if student['subjects'] else None
            audit(db,user['staff_id'],'education_view_progress',sid)
            return {'school':info,'students':students,'method':'Equal-weight mean of latest recorded percentages by subject. Missing results are excluded. Change compares the two latest assessments in a subject; difficulty may differ. Below-target results suggest teacher review, not a diagnosis.'}
    return r
