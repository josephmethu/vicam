const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const base=process.env.SMOKE_ORIGIN;let cookie='';const calls=[];
async function req(path,o={}){const headers={...o.headers};if(cookie&&o.credentials!=='omit')headers.Cookie=cookie;const r=await fetch(base+path,{...o,headers});const c=r.headers.get('set-cookie');if(c)cookie=c.split(';')[0];calls.push({path,...o});return r}
async function waitFor(check,label){for(let n=0;n<150;n++){if(check())return;await new Promise(r=>setTimeout(r,20))}throw Error('Timed out: '+label)}
(async()=>{
 const dom=new JSDOM(await(await req('/admin/clients')).text(),{url:base+'/admin/clients',runScripts:'outside-only'}),w=dom.window;
 w.fetch=req;w.confirm=()=>true;w.HTMLAnchorElement.prototype.click=function(){};
 w.eval((await(await req('/assets/pricing-editor.js')).text())+'\n'+(await(await req('/assets/crm.js')).text())+'\n');const $=id=>w.document.getElementById(id),submit=id=>$(id).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
 await waitFor(()=>$('login-view').hidden===false,'login view');
 $('login-form').elements.email.value='staff@example.com';$('login-form').elements.password.value='local-smoke-password';submit('login-form');
 await waitFor(()=>$('summary').children.length===5,'authenticated summary');
 async function add(kind,values){const tab=Array.from($('tabs').children).find(b=>b.dataset.kind===kind);tab.click();$('new-record').click();for(const [key,value]of Object.entries(values))$('field-'+key).value=value;submit('record-form');await waitFor(()=>$('record-message').textContent==='Record saved.'&&!$('save-record').disabled,'save '+kind).catch(e=>{throw Error(e.message+' · '+$('workspace-error').textContent)});return $('record-reference').textContent}
 const cref=await add('clients',{name:'<script>Client</script>',email:'client@example.com',organization:'Example Firm',notes:'Private client notes.'});assert.match(cref,/CLI-/);assert.equal(w.document.querySelector('#record-list script'),null);
 const client=(await(await req('/api/admin/crm/clients')).json()).items[0];
 await add('projects',{client_id:client.id,title:'Office network',status:'active',assigned_to:'1',due_date:'2026-10-03'});
 const project=(await(await req('/api/admin/crm/projects')).json()).items[0];
 await add('tasks',{client_id:client.id,project_id:project.id,title:'Follow up with client',due_date:'2000-01-01',assigned_to:'1'});
 assert.match($('record-list').textContent,/Overdue/);
 await add('quotes',{client_id:client.id,project_id:project.id,title:'Support quotation',description:'Annual office support',amount_minor:'123.45',currency:'KES',status:'sent'});
 $('print-record').click();await waitFor(()=>$('record-message').querySelector('a'),'draft PDF');assert(!$('sign-record').disabled);await waitFor(()=>$('copy-list').textContent.includes('Withdraw'),'copy history');
 $('sign-record').click();await waitFor(()=>$('record-message').textContent.includes('Signed original saved.'),'signed PDF');
 const quote=(await(await req('/api/admin/crm/quotes')).json()).items[0];
 const original=(await(await req('/api/admin/documents/quotes/'+quote.id+'/copies')).json()).items.find(x=>x.signing_mode==='test');assert(original);
 const pdf=await(await req('/api/admin/documents/copies/'+original.id+'/pdf')).arrayBuffer();assert.equal(Buffer.from(pdf).subarray(0,4).toString(),'%PDF');
 // Obtain the verification token from the PDF's visible URL using server-generated metadata in a second copy.
 const csrf=(await(await req('/api/auth/me')).json()).csrf;
 const issuedCopy=await(await req('/api/admin/documents/quotes/'+quote.id+'/copies',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}'})).json();
 const verifyUrl=issuedCopy.verification_url,token=new URL(verifyUrl).hash.slice(1);const verified=await(await req('/api/verify/'+token,{credentials:'omit'})).json();assert.equal(verified.state,'current');assert(verified.live.checked_at);assert.equal(verified.issuer.name,'VICAM');assert.equal(verified.snapshot.amount_minor,12345);
 const view=new JSDOM(await(await req('/verify/')).text(),{url:verifyUrl,runScripts:'outside-only'});view.window.fetch=req;Object.defineProperty(view.window.crypto,'subtle',{value:require('node:crypto').webcrypto.subtle});view.window.eval(await(await req('/assets/verify.js')).text());await waitFor(()=>view.window.document.getElementById('verify-state').dataset.state==='current','public verification view');assert.equal(view.window.document.querySelector('#verify-fields script'),null);assert.match(view.window.document.getElementById('verify-fields').textContent,/KES 123.45/);assert.equal(view.window.document.getElementById('pdf-check').hidden,false);
 const publicPdf=await(await req(verified.download_url,{credentials:'omit'})).arrayBuffer();
 const fileInput=view.window.document.getElementById('check-file');Object.defineProperty(fileInput,'files',{configurable:true,value:[{size:publicPdf.byteLength,arrayBuffer:async()=>publicPdf}]});fileInput.dispatchEvent(new view.window.Event('change'));await waitFor(()=>view.window.document.getElementById('file-result').textContent.includes('Exact match'),'file match');
 Object.defineProperty(fileInput,'files',{configurable:true,value:[{size:4,arrayBuffer:async()=>Uint8Array.from([1,2,3,4]).buffer}]});fileInput.dispatchEvent(new view.window.Event('change'));await waitFor(()=>view.window.document.getElementById('file-result').textContent.includes('differs'),'altered file warning');view.window.close();
 $('record-list').querySelector('button').click();await waitFor(()=>$('copy-list').textContent.includes(issuedCopy.id.slice(0,8)),'refreshed copy history');Array.from($('copy-list').children).find(row=>row.textContent.includes(issuedCopy.id.slice(0,8))).querySelector('button:last-child').click();await waitFor(()=>$('copy-list').textContent.includes('Withdrawn'),'copy withdrawal');assert.equal((await(await req('/api/verify/'+token,{credentials:'omit'})).json()).state,'withdrawn');
 await add('invoices',{client_id:client.id,project_id:project.id,title:'Support invoice',amount_minor:'123.45',currency:'KES',status:'issued'});
 const invoice=(await(await req('/api/admin/crm/invoices')).json()).items[0];
 await add('payments',{invoice_id:invoice.id,amount_minor:'23.45',paid_date:'2026-10-02',method:'mpesa',external_reference:'TEST-RECEIPT'});
 assert.equal((await(await req('/api/admin/crm/invoices/'+invoice.id)).json()).balance_minor,10000);
 await add('tickets',{client_id:client.id,project_id:project.id,title:'Wi-Fi disconnects',priority:'high',assigned_to:'1'});
 await add('contracts',{client_id:client.id,title:'Annual support agreement',start_date:'2026-10-01',end_date:'2027-10-01',assigned_to:'1'});
 // Invalid date order must show the server validation message and keep the form.
 $('field-end_date').value='2025-10-01';submit('record-form');await waitFor(()=>$('workspace-error').textContent.includes('End date'),'validation feedback');assert.equal($('field-title').value,'Annual support agreement');
 // Exercise the actual calculated-pricing form, saving and issuing its exact copy.
 Array.from($('tabs').children).find(b=>b.dataset.kind==='quotes').click();$('new-record').click();$('field-client_id').value=client.id;$('field-title').value='Calculated installation';$('field-status').value='sent';$('calculated-pricing').checked=true;$('calculated-pricing').dispatchEvent(new w.Event('change'));const pricingRow=$('pricing-lines').querySelector('.pricing-line');pricingRow.querySelector('[data-field=description]').value='Camera installation';pricingRow.querySelector('[data-field=quantity]').value='2';pricingRow.querySelector('[data-field=unit]').value='100.00';$('discount-percent').value='10';$('vat-percent').value='16';$('vat-percent').dispatchEvent(new w.Event('input',{bubbles:true}));await waitFor(()=>$('field-amount_minor').value==='208.80','calculated discount and VAT preview');submit('record-form');await waitFor(()=>$('record-message').textContent==='Record saved.'&&!$('save-record').disabled,'calculated quotation save');assert($('calculated-pricing').checked);$('print-record').click();await waitFor(()=>$('record-message').querySelector('a'),'calculated quotation PDF');
 assert(calls.filter(c=>['POST','PUT','DELETE'].includes(c.method)&&c.path.startsWith('/api/admin/')).every(c=>c.headers['X-CSRF-Token']));
 $('logout').click();await waitFor(()=>$('workspace').hidden,'logout');assert.equal($('record-fields').children.length,0);dom.window.close();
 // Link an enquiry in the original inbox using the same account.
 const enq=await(await req('/api/enquiries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Example Client',email:'client@example.com',service:'Managed IT Support',requirements:'Please support our office computers.',consent:true})})).json();
 const inbox=new JSDOM(await(await req('/admin')).text(),{url:base+'/admin',runScripts:'outside-only'}),i=inbox.window;i.fetch=req;i.confirm=()=>true;i.eval(await(await req('/assets/admin.js')).text());const get=id=>i.document.getElementById(id);
 get('login-form').elements.email.value='staff@example.com';get('login-form').elements.password.value='local-smoke-password';get('login-form').dispatchEvent(new i.Event('submit',{bubbles:true,cancelable:true}));await waitFor(()=>get('enquiry-list').querySelector('button'),'inbox list');
 get('enquiry-list').querySelector('button').click();await waitFor(()=>get('link-client').options.length>1,'client options');get('link-client').value=client.id;get('convert-client').click();await waitFor(()=>get('client-link-status').querySelector('a'),'linked client');assert.match(get('client-link-status').textContent,/Open/);
 const detail=await(await req('/api/admin/crm/clients/'+client.id)).json();assert.equal(detail.enquiries[0].reference,enq.reference);
 inbox.window.close();console.log('Actual HTTP + DOM checks passed: staff login, all eight CRM modules, calculated pricing/discount/VAT, exact money conversion, server PDF downloads/public verification/file comparison/withdrawal, validation, logout cleanup and enquiry-to-client linking.');
})().catch(e=>{console.error(e);process.exitCode=1});
