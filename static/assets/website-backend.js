'use strict';
const enquiryForm=document.getElementById('project-form');
const sendButton=enquiryForm.querySelector('button[type=submit]');
const receipt=document.getElementById('project-status');
let submissionKey='',submittedPayload='';
async function connectWebsite(){
  if(location.protocol==='file:'){receipt.textContent='Online submission is unavailable in this file. You can still save a brief to your device.';return}
  try{
    const response=await fetch('/api/public/config',{credentials:'same-origin'});
    if(!response.ok)throw new Error();
    const config=await response.json();
    if(!config.enquiries_available)throw new Error();
    sendButton.disabled=false;
    receipt.textContent='Your brief will be received by VICAM. You can also save a copy to your device.';
    document.querySelector('.contact-intro>p').textContent='Have a project in mind? Share a few details so VICAM can understand what you need.';
    const contact=document.querySelector('.contact-pending');
    if(config.company_email){contact.querySelector('h3').textContent='Email VICAM';contact.querySelector('p').textContent='For enquiries and follow-ups, reach our team at:';const link=document.createElement('a');link.className='backend-contact-email';link.href='mailto:'+config.company_email;link.textContent=config.company_email;contact.append(link)}
    else{contact.querySelector('h3').textContent='Start with your project brief.';contact.querySelector('p').textContent='Your brief goes to VICAM’s enquiry inbox. Add an email address so the team can follow up.'}
  }catch{sendButton.disabled=true;receipt.textContent='Online submission is unavailable right now. Save your brief and try again later.'}
}
enquiryForm.addEventListener('submit',async event=>{
  event.preventDefault();
  if(sendButton.disabled||!enquiryForm.reportValidity())return;
  const consent=document.getElementById('project-consent');
  if(!consent.checked){receipt.textContent='Please accept the enquiry privacy notice before sending your brief.';consent.focus();return}
  const fields=new FormData(enquiryForm);const payload={};
  for(const key of ['name','email','service','requirements','organization','phone','timeline','site_type','existing_system','coverage_areas','website'])payload[key]=String(fields.get(key)||'').trim();
  payload.service_context=['context-one','context-two'].map(id=>{const f=document.getElementById(id);return !f.disabled&&f.value.trim()?f.previousElementSibling.textContent+': '+f.value.trim():''}).filter(Boolean).join('\n');
  payload.consent=true;
  const serialized=JSON.stringify(payload);
  if(serialized!==submittedPayload){submissionKey=crypto.randomUUID();submittedPayload=serialized}
  sendButton.disabled=true;receipt.textContent='Sending your brief…';
  try{
    const response=await fetch('/api/enquiries',{method:'POST',headers:{'Content-Type':'application/json','X-Idempotency-Key':submissionKey},body:serialized,credentials:'same-origin'});
    const result=await response.json();
    if(!response.ok){throw new Error(typeof result.detail==='string'?result.detail:(response.status===422?'Please check your name, email and project details.':'Your brief could not be submitted. Please try again.'))}
    receipt.textContent='Your brief has been received. Reference: '+result.reference+'. Keep this reference. VICAM will review your brief and contact you using the details provided to clarify the scope and next steps.';
    enquiryForm.reset();syncProjectFields();updateServiceGuidance();submissionKey='';submittedPayload='';
  }catch(error){receipt.textContent=error.message||'Unable to send. Your details are still in the form; you can save a copy or try again.'}
  finally{sendButton.disabled=false}
});
connectWebsite();
