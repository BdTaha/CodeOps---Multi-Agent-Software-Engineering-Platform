import fs from 'node:fs';
import { spawnSync, spawn } from 'node:child_process';
const profile=JSON.parse(process.argv[3]);
const env={...process.env,...profile.environment};
if(process.argv[2]==='build') {
  const commands=[];
  if(fs.existsSync('package.json')) {
    if(!fs.existsSync('package-lock.json')) throw new Error('Node previews require package-lock.json for npm ci.');
    commands.push(['npm','ci','--no-audit','--no-fund']);
  }
  commands.push(...profile.build_commands);
  for(const command of commands) { const result=spawnSync(command[0],command.slice(1),{env,stdio:'inherit',shell:false}); if(result.error)throw result.error; if(result.status!==0)process.exit(result.status??1); }
} else {
  const child=spawn(profile.start_command[0],profile.start_command.slice(1),{env,stdio:'inherit',shell:false});
  for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>child.kill(signal));
  child.on('error',error=>{console.error(error);process.exit(1);});
  child.on('exit',code=>process.exit(code??1));
}
