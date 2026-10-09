"""Server-enforced staff role matrix. Unmatched admin routes fail closed."""
from fastapi import HTTPException
ROLES={'admin','finance','support'}

def authorize(role,path,method):
    if role not in ROLES:raise HTTPException(403,'Staff role is invalid; contact the administrator')
    if not path.startswith('/api/admin/'):return
    if role=='admin':return
    read=method in {'GET','HEAD'}
    allowed=False
    if path=='/api/admin/assistant/query':allowed=method=='POST'
    elif path=='/api/admin/assistant/config':allowed=read
    elif path.startswith('/api/admin/crm/'):
        part=path.split('/')[4]
        if part in {'summary','staff'}:allowed=read
        elif role=='finance':allowed=part in {'quotes','invoices','payments','calculate'} and method!='DELETE' or part in {'clients','projects'} and read
        else:allowed=part in {'clients','projects','tasks','tickets','contracts','convert'} and method!='DELETE'
    elif path.startswith('/api/admin/documents/'):
        allowed=role=='finance'
    elif path.startswith('/api/admin/enquiries'):
        allowed=role=='support' and method!='DELETE'
    elif path.startswith('/api/admin/experience/'):
        rest=path[len('/api/admin/experience/'):].split('/')
        if role=='finance':allowed=rest[0]=='decisions' and read or rest[0]=='clients' and len(rest)>2 and rest[2]=='documents'
        else:
            allowed=rest[0] in {'projects','tickets','files','follow-ups','equipment','reports','service-dashboard'} and method!='DELETE'
            if rest[0]=='clients' and len(rest)>2:allowed=rest[2] in {'access','invite','files','equipment','reports','timeline'} and method!='DELETE'
    elif path.startswith('/api/admin/delivery/'):
        allowed=role=='finance' and not path.endswith('/jobs')
    if not allowed:raise HTTPException(403,'Your staff role does not allow this action')
