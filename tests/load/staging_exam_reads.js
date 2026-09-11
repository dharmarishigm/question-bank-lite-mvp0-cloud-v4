// k6 run -e BASE_URL=https://qb-security-staging-...run.app -e SESSION_FILE=/secure/sessions.json tests/load/staging_exam_reads.js
import http from 'k6/http';
import {check,sleep} from 'k6';
import {SharedArray} from 'k6/data';
const base=__ENV.BASE_URL||'';
if(!/^https:\/\/qb-security-staging-[a-z0-9-]+\.run\.app$/.test(base))throw Error('Only the isolated staging service is permitted');
const sessions=new SharedArray('synthetic users',()=>JSON.parse(open(__ENV.SESSION_FILE)));
const peak=Number(__ENV.PEAK_USERS||100);
if(![100,1000,5000,10000].includes(peak)||sessions.length<peak)throw Error('Provide one distinct synthetic session per virtual user and an approved ramp size');
export const options={stages:[{duration:'2m',target:peak},{duration:'5m',target:peak},{duration:'1m',target:0}],thresholds:{http_req_failed:['rate<0.01'],http_req_duration:['p(95)<1000','p(99)<2500']}};
export default function(){const user=sessions[__VU-1];const r=http.get(base+'/api/my/exams',{headers:{Cookie:'qb_session='+user.session}});check(r,{'authenticated read succeeds':r=>r.status===200});sleep(5);}
