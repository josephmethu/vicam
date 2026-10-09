from test_backend import client,signin
from app.db import connect,initialize
from app.security import hash_password
BASE='/api/admin/education/schools'
def create(c,h,path,data):
    r=c.post(path,json=data,headers=h);assert r.status_code==201,r.text;return r.json()
def setup(c,h):
    school=create(c,h,BASE,{'name':'Example School','target':60});base=BASE+'/'+school['id'];st=create(c,h,base+'/students',{'code':'S1','name':'Learner One','class_name':'Class 1'});sub=create(c,h,base+'/subjects',{'name':'Maths'});return base,st,sub
def assessment(c,h,b,sub,day,max_score):return create(c,h,b+'/assessments',{'subject_id':sub['id'],'title':day,'topic':'Fractions','class_name':'Class 1','assessed_on':day,'max_score':max_score})
def save(c,h,b,a,items):return c.put(b+'/assessments/'+a['id']+'/results',json={'items':items},headers=h)
def test_education_access_owner_role_and_csrf(client):
    assert client.get(BASE).status_code==401
    h=signin(client);b,st,sub=setup(client,h)
    assert client.post(b+'/students',json={'code':'S2','name':'Two','class_name':'Class 1'}).status_code==403
    with connect(client.settings.db_path) as db:db.execute("INSERT INTO staff(email,password_hash,role) VALUES(?,?,'admin')",('other@example.com',hash_password('other-long-password')))
    client.post('/api/auth/logout',json={},headers=h);r=client.post('/api/auth/login',json={'email':'other@example.com','password':'other-long-password'});other={'X-CSRF-Token':r.json()['csrf']}
    assert client.get(BASE).json()['items']==[]
    assert client.get(b+'/workspace').status_code==404 and client.get(b+'/progress').status_code==404
    assert client.post(b+'/students',json={'code':'X','name':'X','class_name':'Class 1'},headers=other).status_code==404
    for role in ['finance','support']:
        with connect(client.settings.db_path) as db:db.execute('UPDATE staff SET role=? WHERE email=?',(role,'other@example.com'))
        assert client.get(BASE).status_code==403
    page=client.get('/admin/education');assert page.status_code==200 and "script-src 'self';" in page.headers['content-security-policy']
def test_education_result_bounds_cross_school_atomic_and_migration(client):
    h=signin(client);b,st,sub=setup(client,h);a=assessment(client,h,b,sub,'2026-01-01',50);assert save(client,h,b,a,[{'student_id':st['id'],'score':30}]).status_code==200
    for score in [-1,51,'NaN','Infinity']:assert save(client,h,b,a,[{'student_id':st['id'],'score':score}]).status_code==422
    b2,st2,sub2=setup(client,h)
    assert save(client,h,b,a,[{'student_id':st['id'],'score':20},{'student_id':st2['id'],'score':10}]).status_code==404
    assert client.get(b+'/assessments/'+a['id']+'/results').json()['items'][0]['score']==30
    assert save(client,h,b,a,[{'student_id':st['id'],'score':20}]*2).status_code==422
    other=create(client,h,b+'/students',{'code':'S3','name':'Other','class_name':'Class 2'});assert save(client,h,b,a,[{'student_id':other['id'],'score':10}]).status_code==422
    assert client.delete(b+'/students/'+st['id'],headers=h).status_code==409
    assert client.post(b+'/students',json={'code':'S1','name':'Duplicate','class_name':'Class 1'},headers=h).status_code==409
    wrong={'subject_id':sub2['id'],'title':'Wrong','class_name':'Class 1','assessed_on':'2026-01-01','max_score':100};assert client.post(b+'/assessments',json=wrong,headers=h).status_code==404
    wrong.update(subject_id=sub['id'],assessed_on='2099-01-01');assert client.post(b+'/assessments',json=wrong,headers=h).status_code==422
    initialize(client.settings.db_path);assert client.get(b+'/workspace').status_code==200
    with connect(client.settings.db_path) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==8
    assert client.put(b+'/students/'+st['id'],json={'code':'S1','name':'One','class_name':'Class 2'},headers=h).status_code==409
def test_education_progress_percentage_missing_zero_and_target(client):
    h=signin(client);b,st,sub=setup(client,h);missing=create(client,h,b+'/students',{'code':'S2','name':'Missing','class_name':'Class 1'});new=assessment(client,h,b,sub,'2026-02-01',50);old=assessment(client,h,b,sub,'2026-01-01',100)
    save(client,h,b,old,[{'student_id':st['id'],'score':40}]);save(client,h,b,new,[{'student_id':st['id'],'score':35}])
    def learner(identifier):return next(x for x in client.get(b+'/progress').json()['students'] if x['id']==identifier)
    p=learner(st['id']);assert p['latest_subject_average']==70 and p['subjects'][0]['change_points']==30 and not p['subjects'][0]['focus'];assert learner(missing['id'])['latest_subject_average'] is None
    save(client,h,b,new,[{'student_id':missing['id'],'score':0}]);assert learner(missing['id'])['latest_subject_average']==0 and learner(missing['id'])['subjects'][0]['focus']
    save(client,h,b,new,[{'student_id':missing['id'],'score':None}]);assert learner(missing['id'])['latest_subject_average'] is None
    assert client.put(b,json={'name':'School','target':80},headers=h).status_code==200;assert learner(st['id'])['subjects'][0]['focus']
    with connect(client.settings.db_path) as db:assert db.execute("SELECT count(*) FROM audit WHERE action='education_save_results'").fetchone()[0]>0
