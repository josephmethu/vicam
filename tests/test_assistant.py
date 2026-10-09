import json
from dataclasses import replace
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse,parse_qs
import pytest
from test_backend import client,signin
from test_crm import create,profile,issued,payment,BASE
from app import assistant
from app.db import connect

PATH='/api/admin/assistant/'
def ask(c,h,q,**kw):return c.post(PATH+'query',json=dict(question=q,**kw),headers=h)

def test_auth_csrf_roles_and_help(client):
    assert client.get(PATH+'config').status_code==401
    h=signin(client)
    assert ask(client,{},'Show invoices').status_code==403
    assert client.get(PATH+'config').json()==dict(ai_configured=False,mode='local_navigation',read_only=True)
    assert 'Record a payment' in ask(client,h,'How do I record a payment?').text
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='support'")
    assert ask(client,h,'Show unpaid invoices').status_code==403
    assert ask(client,h,'How do I record a payment?').status_code==403
    assert ask(client,h,'How do I invite a client?').status_code==200
    assert ask(client,h,'Show open tickets').status_code==200
    with connect(client.settings.db_path) as db:db.execute("UPDATE staff SET role='finance'")
    assert ask(client,h,'How do I check backups?').status_code==403
    assert ask(client,h,'How do I invite a client?').status_code==403
    assert ask(client,h,'Show unpaid invoices').status_code==200

def test_unpaid_and_filtered_links(client):
    h=signin(client);c=profile(client,h)
    a=issued(client,h,c['id']);b=issued(client,h,c['id'])
    create(client,'payments',payment(b,10000),h)
    create(client,'invoices',dict(client_id=c['id'],title='Draft',amount_minor=500),h)
    result=ask(client,h,'Show unpaid invoices').json()
    assert result['total']==1 and result['items'][0]['url'].endswith(a['id'])
    query=parse_qs(urlparse(result['view_url']).query)
    assert client.get(BASE+'invoices',params={'assistant_filter':query['assistant_filter'][0]}).json()['total']==1
    assert client.get(BASE+'clients',params={'assistant_filter':'unpaid'}).status_code==422

def test_week_dates_client_match_and_limit(client):
    h=signin(client);c=profile(client,h,'Acme');other=profile(client,h,'Other')
    today=datetime.now(ZoneInfo(client.settings.business_timezone)).date();end=today+timedelta(days=6-today.weekday())
    for due in [today,end+timedelta(days=1),today-timedelta(days=1)]:
        create(client,'quotes',dict(client_id=c['id'],title='Quote',status='sent',amount_minor=1000,due_date=due.isoformat()),h)
    assert ask(client,h,'Which quotations expire this week?').json()['total']==1
    for i in range(11):create(client,'projects',dict(client_id=c['id'],title=f'Project {i}'),h)
    create(client,'projects',dict(client_id=other['id'],title='Other project'),h)
    result=ask(client,h,'Show projects for Acme').json()
    assert result['total']==11 and len(result['items'])==10
    assert parse_qs(urlparse(result['view_url']).query)['client_filter']==[c['id']]
    profile(client,h,'Acme Two')
    ambiguous=ask(client,h,'Show projects for Acme').json()
    assert len(ambiguous['items'])==2 and 'Choose' in ambiguous['message']
    assert all('client_filter=' in x['url'] and 'record=' not in x['url'] for x in ambiguous['items'])
    assert ask(client,h,'Find client %').json()['total']==0

def test_no_mutations_or_question_logs(client,monkeypatch):
    h=signin(client);c=profile(client,h,'Private Name')
    def fail(*a):raise AssertionError('AI must not be called')
    monkeypatch.setattr(assistant,'ai_intent',fail)
    for question in ['Delete client Private Name','Send invoice to Private Name','Create a quotation']:
        result=ask(client,h,question,use_ai=True)
        assert result.status_code==200 and result.json()['items']==[]
    assert client.get(BASE+'clients/'+c['id']).status_code==200
    ask(client,h,'Find client Private Name')
    with connect(client.settings.db_path) as db:
        logs=str([tuple(r) for r in db.execute("SELECT * FROM audit WHERE action='assistant_lookup'")])
        assert 'Private Name' not in logs
    assert ask(client,h,'Show invoices',use_ai='true').status_code==422

def test_optional_ai_request_schema_and_fallback(client,monkeypatch):
    h=signin(client)
    assert 'not configured' in ask(client,h,'Locate receivables',use_ai=True).json()['message']
    settings=replace(client.settings,assistant_ai_key='test-key',assistant_ai_model='test-model')
    intent=dict(kind='invoices',filter='unpaid',search='',client_search='',help_topic='none')
    captured={}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return json.dumps(dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(intent))])])).encode()
    def fake(req,timeout):captured.update(json.loads(req.data));assert timeout==12;return Response()
    monkeypatch.setattr(assistant,'urlopen',fake)
    assert assistant.ai_intent(settings,'Locate receivables').kind=='invoices'
    assert captured['input']=='Locate receivables' and captured['store'] is False
    schema=captured['text']['format']['schema'];assert schema['additionalProperties'] is False and set(schema['required'])==set(intent)
    # API closure uses the settings created with the app; replace the app for enabled mode.
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings,enable_mail_worker=False)) as c:
        headers=signin(c)
        assert ask(c,headers,'Locate receivables',use_ai=True).json()['mode']=='ai_navigation'
        with connect(settings.db_path) as db:db.execute("UPDATE staff SET role='support'")
        assert ask(c,headers,'Locate receivables',use_ai=True).status_code==403
        def unavailable(*a):raise TimeoutError()
        monkeypatch.setattr(assistant,'ai_intent',unavailable)
        fallback=ask(c,headers,'Locate receivables',use_ai=True).json()
        assert fallback['mode']=='local_navigation' and 'unavailable' in fallback['message']


def test_tasks_today_excludes_past_and_closed(client):
    h=signin(client);c=profile(client,h)
    today=datetime.now(ZoneInfo(client.settings.business_timezone)).date()
    for due,status in [(today,'open'),(today-timedelta(days=1),'open'),(today,'done')]:
        create(client,'tasks',dict(client_id=c['id'],title='Task',due_date=due.isoformat(),status=status),h)
    result=ask(client,h,'Show tasks due today').json()
    assert result['total']==1
    assert client.get(BASE+'tasks',params={'assistant_filter':'due_today'}).json()['total']==1
    assert ask(client,h,'Show overdue tasks').json()['total']==1
