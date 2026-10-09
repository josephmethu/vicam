'use strict';
const kit={
 csrf:'',
 el(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x},
 feedback(message,error=false){const x=document.getElementById('feedback');x.textContent=message;x.className='feedback '+(error?'error':'notice')},
 async api(path,options={}){const headers={...options.headers};if(options.body){headers['Content-Type']='application/json';headers['X-CSRF-Token']=kit.csrf}const r=await fetch(path,{...options,headers,credentials:'same-origin'});const v=await r.json();if(!r.ok){if(r.status===401){kit.csrf='';document.dispatchEvent(new Event('session-expired'))}throw Error(typeof v.detail==='string'?v.detail:Array.isArray(v.detail)?v.detail.map(x=>x.msg).join('; '):'Unable to complete this action')}return v},
 async all(kind,params=''){let items=[],page=1,data;do{data=await kit.api('/api/admin/crm/'+kind+'?page='+page++ +params);items.push(...data.items)}while(items.length<data.total&&data.items.length);return items},
 options(select,items,first='Choose…'){const previous=select.value;select.replaceChildren(new Option(first,''));for(const x of items)select.add(new Option(x.name||x.title||x.reference,x.id));if(items.some(x=>x.id===previous))select.value=previous},
 form(form){return Object.fromEntries(new FormData(form))},
 async run(button,fn){button.disabled=true;kit.feedback('');try{await fn()}catch(e){kit.feedback(e.message,true)}finally{button.disabled=false}},
 date(s){return s?new Date(s).toLocaleString():''},
 money(v,c){return c+' '+(v/100).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})},
 link(text,url){const a=kit.el('a',text);a.href=url;return a},
 item(parent,title,detail){const d=kit.el('div',undefined,'item');d.append(kit.el('strong',title));if(detail)d.append(kit.el('p',detail,'muted'));parent.append(d);return d},
 async filePayload(form){const input=form.querySelector('input[type=file]'),f=input.files[0];if(!f)throw Error('Choose a file');if(f.size>2*1024*1024)throw Error('Maximum file size is 2 MB');const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return {name:f.name,project_id:form.elements.project_id.value||null,content_base64:btoa(binary)}}
};
document.querySelectorAll('nav.tabs button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('nav.tabs button').forEach(x=>x.setAttribute('aria-selected',String(x===b)));document.querySelectorAll('[data-panel]').forEach(x=>x.hidden=x.dataset.panel!==b.dataset.tab)}));
