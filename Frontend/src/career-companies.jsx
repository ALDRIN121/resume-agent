import React from 'react';
import { Button,Card,EmptyState } from './components.jsx';
import { listCompanies,getRun } from './api/client.js';

export function CareerCompanies({goto,openRun}) {
  const [rows,setRows]=React.useState(null),[error,setError]=React.useState(null);
  const refresh=async()=>{setError(null);try{const data=await listCompanies();if(!Array.isArray(data))throw new Error('Company counts are unavailable.');setRows(data);}catch(e){setError(e.message);setRows(null);}};
  React.useEffect(()=>{refresh();},[]);
  const open=async company=>{
    try{if(company.latest_run_id){const run=await getRun(company.latest_run_id);openRun(run.id,run.status,run);}else if(company.latest_job_id)goto('jobs',{jobId:company.latest_job_id});}
    catch(e){setError(e.message);}
  };
  return <main className="page-pad" style={{padding:32,maxWidth:1240}}><h1>Companies</h1>
    <p>Saved jobs, documents and application records have separate counts. Submissions come only from explicit recorded events.</p>
    <Button variant="ghost" onClick={refresh}>Refresh companies</Button>
    {error&&<p role="alert">{error}</p>}
    {rows===null&&!error?<p>Loading company records…</p>:rows?.length===0?<Card padding={0}><EmptyState icon="building" title="No companies yet" sub="Save a role or create a resume to add a company." action={<Button onClick={()=>goto('jobs')}>Save a role</Button>}/></Card>:<div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))',gap:16,marginTop:20}}>{rows?.map(company=><Card key={company.name} padding={20}>
      <h2>{company.unknown_company?'Company not supplied':company.name}</h2>
      <p>{company.jobs||0} saved job{company.jobs===1?'':'s'}</p><p>{company.total||0} document run{company.total===1?'':'s'}</p>
      <p>{company.final||0} final · {company.failed||0} failed · {company.cancelled||0} cancelled</p>
      <p>{company.applications||0} application record{company.applications===1?'':'s'}</p><p>{company.submitted||0} submitted</p>
      <p>{company.positive||0} with positive evidence</p><p>{company.responses||0} with recorded replies</p>
      {(company.latest_run_id||company.latest_job_id)&&<Button variant="secondary" onClick={()=>open(company)}>{company.latest_run_id?'View document run':'View saved role'}</Button>}
    </Card>)}</div>}
  </main>;
}
