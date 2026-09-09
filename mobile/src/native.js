import {Capacitor,registerPlugin} from '@capacitor/core';
import {App} from '@capacitor/app';
import {Network} from '@capacitor/network';
import {PushNotifications} from '@capacitor/push-notifications';
import {Share} from '@capacitor/share';
const Native=registerPlugin('MeritIQra');
if(Capacitor.isNativePlatform()){
 const original=window.fetch.bind(window);
 window.MeritIQraNative={Native,version:MOBILE_VERSION};
 window.fetch=async(input,options={})=>{
  const target=typeof input==='string'?input:input.url;const url=new URL(target,location.origin);
  if(url.origin!==location.origin || !url.pathname.startsWith('/api/'))return original(input,options);
  let body=options.body??null;let files=null;
  if(body instanceof FormData){files=[];const fields={};for(const [key,value] of body.entries()){if(value instanceof Blob){if(value.size>50*1024*1024)throw Error('Maximum upload is 50 MB');const bytes=new Uint8Array(await value.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));files.push({key,name:value.name,type:value.type,data:btoa(binary)});}else fields[key]=value;}body=JSON.stringify(fields);}
  const response=await Native.request({path:url.pathname+url.search,method:options.method||'GET',body,files});
  return new Response(response.body,{status:response.status,headers:{'Content-Type':'application/json'}});
 };
 window.addEventListener('DOMContentLoaded',()=>{
  document.body.classList.add('native-mobile');
  document.getElementById('google-signin').replaceChildren();
  const login=document.createElement('button');login.textContent='Continue with Google';login.className='primary';login.onclick=()=>Native.signIn();document.getElementById('google-signin').append(login);const explore=document.createElement('button');explore.textContent='Explore public exams';explore.onclick=()=>Native.explorePublic();document.getElementById('google-signin').append(explore);
  document.getElementById('login-message').textContent='Sign in securely in your browser, then return to MeritIQra.';
  const nav=document.createElement('nav');nav.className='mobile-bottom-nav';nav.setAttribute('aria-label','Learning navigation');for(const [view,label] of [['dashboard','Home'],['available-exams','Explore'],['my-exams','My Exams'],['student-analytics','Performance'],['my-profile','Profile']]){const b=document.createElement('button');b.textContent=label;b.onclick=()=>window.dispatchEvent(new CustomEvent('mobile:navigate',{detail:view}));b.dataset.view=view;nav.append(b);}document.body.append(nav);const preferences=document.createElement('section');preferences.className='panel';preferences.innerHTML='<h3>Notifications</h3><p>Optional alerts contain no scores or personal details.</p><button data-push-enable>Enable notifications</button> <button data-push-disable>Turn off notifications</button><p role="status"></p>';preferences.querySelector('[data-push-enable]').onclick=async()=>{const message=preferences.querySelector('[role=status]');try{const config=await (await fetch('/api/mobile/config')).json();if(!config.push_available){message.textContent='Notifications are not configured for this deployment yet.';return;}await window.enableMobileNotifications();message.textContent='Notification permission updated.';}catch{message.textContent='Could not enable notifications. Please try again.';}};preferences.querySelector('[data-push-disable]').onclick=async()=>{await fetch('/api/mobile/devices',{method:'DELETE'});await PushNotifications.unregister().catch(()=>{});preferences.querySelector('[role=status]').textContent='Notifications disabled.';};document.getElementById('my-profile-panel').append(preferences);
 });
 window.addEventListener('mobile:login',({detail:user})=>{document.body.dataset.nativeRole=user.role;const nav=document.querySelector('.mobile-bottom-nav');if(nav&&user.role!=='STUDENT'){nav.replaceChildren();for(const [view,label] of [['dashboard','Home'],['admin-exams','Exams'],['admin-results','Results'],['my-profile','Profile']]){const button=document.createElement('button');button.textContent=label;button.onclick=()=>window.dispatchEvent(new CustomEvent('mobile:navigate',{detail:view}));nav.append(button);}}});
 const updateNetwork=s=>window.dispatchEvent(new CustomEvent('mobile:network',{detail:s.connected}));Network.addListener('networkStatusChange',updateNetwork);Network.getStatus().then(updateNetwork);
 App.addListener('appStateChange',async({isActive})=>{if(isActive){await Native.completeSignIn().catch(()=>{});window.dispatchEvent(new Event('mobile:resume'));}else window.dispatchEvent(new Event('mobile:background'));});
 App.addListener('backButton',()=>window.dispatchEvent(new Event('mobile:back')));
 App.getLaunchUrl().then(result=>{if(result?.url)Native.acceptLink({url:result.url}).then(()=>window.dispatchEvent(new Event('mobile:resume')));});
 App.addListener('appUrlOpen',({url})=>Native.acceptLink({url}).then(()=>window.dispatchEvent(new Event('mobile:resume'))));
 window.enableMobileNotifications=async()=>{const result=await PushNotifications.requestPermissions();if(result.receive==='granted')await PushNotifications.register();};
 PushNotifications.addListener('registration',({value})=>fetch('/api/mobile/devices',{method:'POST',body:JSON.stringify({token:value,enabled:true})}));
 PushNotifications.addListener('pushNotificationActionPerformed',event=>{if(event.notification.data?.action==='results')window.dispatchEvent(new CustomEvent('mobile:navigate',{detail:'my-results'}));const url=event.notification.data?.url;if(url)Native.acceptLink({url}).then(()=>window.dispatchEvent(new Event('mobile:resume')));});
 window.sharePublicExam=async url=>{const target=new URL(url);if(target.origin!==MOBILE_API_BASE||!/^\/(register\/exam\/|exams\/)/.test(target.pathname))throw Error('Only public registration links may be shared');await Share.share({title:'MeritIQra assessment',url});};
}
