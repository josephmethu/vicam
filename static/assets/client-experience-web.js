'use strict';
const serviceHints={
'Quotation & Invoice Verification':['Describe your document workflow','Documents issued each month','Current tools and staff users','Tell us how you prepare and send quotations or invoices, and what recipients need to verify.'],
 'Education & Student Performance':['What learning outcomes would you like to improve?','Age group or education level','Tools currently used','Share the school’s goals and current process, without student names, grades or records.'],
 'Managed IT Support':['What IT work would you like VICAM to manage?','Approximate team or device count','Main systems needing support','Include your support needs and business hours. Do not include passwords or account details.'],
 'Software Development':['What should the software help people do?','Who will use the software?','Existing tools it should connect to','Describe the workflow, main users and the result you want.'],
 'Data & AI':['Which process or decision would you like to improve?','Process to improve','Existing tools or data sources','Describe the problem and types of data available. Do not upload personal or confidential datasets.'],
 'Cybersecurity':['What would you like to protect or review?','Systems or sites in scope','Main concern','Describe your goals without exposing passwords, vulnerabilities or confidential incident details.'],
 'Cloud & Infrastructure':['What needs to connect, move or work more reliably?','Approximate users or sites','Current setup','Share the broad setup and your goals, without credentials or network configuration files.'],
 'CCTV & Surveillance':['What would you like to monitor or protect?','','','Use the optional site questions below to describe your coverage needs.'],
 'Not sure yet':['What are you trying to achieve?','','','Describe your challenge in everyday language. VICAM can help identify the appropriate service.']
};
function updateServiceGuidance(){const selected=document.querySelector('#project-form select[name=service]').value,h=serviceHints[selected]||serviceHints['Not sure yet'],box=document.getElementById('service-context-fields');document.getElementById('requirements-label').textContent=h[0];document.getElementById('service-guidance').textContent=h[3];box.hidden=!h[1];for(const [id,label] of [['context-one',h[1]],['context-two',h[2]]]){const field=document.getElementById(id);field.disabled=!h[1];field.previousElementSibling.textContent=label}document.getElementById('project-form').querySelector('[name=requirements]').placeholder=h[3]}
document.querySelector('#project-form select[name=service]').addEventListener('change',updateServiceGuidance);
window.addEventListener('hashchange',()=>setTimeout(updateServiceGuidance,0));
updateServiceGuidance();
fetch('/api/public/case-studies').then(r=>{if(!r.ok)throw Error();return r.json()}).then(data=>{if(!data.items.length)return;const container=document.getElementById('case-study-cards');for(const x of data.items){const a=document.createElement('article');for(const [tag,text] of [['span',x.service],['h3',x.title],['h4','The challenge'],['p',x.problem],['h4','What VICAM did'],['p',x.solution],['h4','The result'],['p',x.result]]){const e=document.createElement(tag);e.textContent=text;a.append(e)}container.append(a)}document.getElementById('real-projects').hidden=false}).catch(()=>{});
