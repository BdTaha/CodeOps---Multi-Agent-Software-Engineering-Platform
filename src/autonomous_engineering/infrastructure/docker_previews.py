"""Restricted Docker preview adapter. Never executes project commands on the host."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
import urllib.request
import urllib.error
from autonomous_engineering.domain.previews import PreviewProfileInput
from autonomous_engineering.domain.base import utc_now
from autonomous_engineering.infrastructure.delivery import checked_artifact, receipt
from autonomous_engineering.workflows.state import WorkflowState
from sqlalchemy.engine import make_url

class PreviewRuntimeError(RuntimeError): pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class DockerPreviewRuntime:
    def __init__(self, config):
        self.config=config
        identity=make_url(config.database_url.get_secret_value()).set(password=None)
        if identity.get_backend_name()=='sqlite' and identity.database not in {None,':memory:'}:
            identity=identity.set(database=str(Path(identity.database).resolve()))
        self.workspace_key=hashlib.sha256((str(identity)+'|'+str(config.workspace_root.resolve())).encode()).hexdigest()[:24]
        self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def docker(self,*args,input=None,timeout=15,missing_ok=False):
        try:
            result=subprocess.run([self.config.docker_executable,*args],input=input,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise PreviewRuntimeError('Docker unavailable or command timed out; cleanup will be retried.') from exc
        if result.returncode:
            message=result.stderr.decode(errors='replace')[-4000:]
            lowered=message.lower()
            resource_missing=any(text in lowered for text in ('no such container','no such object','no such volume','no such network')) or (args and f'network {args[-1].lower()} not found' in lowered)
            if missing_ok and resource_missing: return None
            raise PreviewRuntimeError(message or 'Docker command failed.')
        return result.stdout.decode(errors='replace').strip()

    def names(self,row):
        stem='codeops-preview-'+row['id']
        return stem+'-build',stem+'-run',stem+'-files',stem+'-net'

    def labels(self,row):
        return {'codeops.preview_id':row['id'],'codeops.workspace':self.workspace_key,
            'codeops.execution_id':row['execution_task_id'],'codeops.run_id':row['run_id']}

    def label_args(self,row):
        return [arg for key,value in self.labels(row).items() for arg in ('--label',key+'='+value)]

    def inspect(self,name,kind='container'):
        raw=self.docker(kind,'inspect',name,missing_ok=True)
        return json.loads(raw)[0] if raw is not None else None

    def owned(self,info,row,kind='container'):
        labels=(info.get('Config',{}).get('Labels') if kind=='container' else info.get('Labels')) or {}
        return all(labels.get(key)==value for key,value in self.labels(row).items())

    def resource(self,row,kind,name):
        info=self.inspect(name,kind)
        if info and not self.owned(info,row,kind): raise PreviewRuntimeError('Resource ownership mismatch; refusing to touch it.')
        return info

    def archive(self,snapshot):
        state=WorkflowState.model_validate(snapshot)
        before=receipt(state,self.config.workspace_root)
        reader=checked_artifact(state,self.config.workspace_root)
        output=io.BytesIO(); digest=hashlib.sha256(); total=0
        with tarfile.open(fileobj=output,mode='w') as archive:
            for name in reader.inventory().files:
                if any(part.casefold().startswith('.env') for part in Path(name).parts): continue
                content=reader.read_text(name).encode('utf-8'); total+=len(content)
                if total>16*1024*1024: raise PreviewRuntimeError('Preview source exceeds the bounded text snapshot limit.')
                digest.update(name.encode()+b'\x00'+content+b'\x00')
                info=tarfile.TarInfo(name);info.size=len(content);info.uid=info.gid=10001;info.mode=0o644
                archive.addfile(info,io.BytesIO(content))
        if before!=receipt(state,self.config.workspace_root): raise PreviewRuntimeError('Reviewed artifact changed during preview materialization.')
        return output.getvalue(),digest.hexdigest()

    def restrictions(self,row,network,runtime=False):
        flags=['--pull=never','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--user=10001:10001','--pids-limit=256','--memory=1g','--memory-swap=1g','--cpus=2',
            '--workdir=/app','--tmpfs=/tmp:rw,nosuid,nodev,size=268435456,mode=1777',
            '--log-driver=json-file','--log-opt=max-size=1m','--log-opt=max-file=2','--network',network,
            '--mount','type=volume,source='+self.names(row)[2]+',target=/app',*self.label_args(row)]
        if runtime:
            policy=Path(__file__).resolve().parents[3]/'containers'/'preview-seccomp.json'
            if not policy.is_file(): raise PreviewRuntimeError('Preview seccomp policy is unavailable; startup refused.')
            flags+=['--security-opt','seccomp='+str(policy.resolve())]
        return flags

    def launch(self,row,snapshot,guard,update):
        profile=PreviewProfileInput.model_validate(json.loads(row['profile_snapshot']))
        build,run,volume,network=self.names(row)
        image=self.config.preview_python_image if profile.runtime=='python' else self.config.preview_node_image
        archive,digest=self.archive(snapshot);guard()
        self.docker('volume','create',*self.label_args(row),volume)
        # Builder exists only while preparation runs. The runtime is created afterward.
        self.docker('create','--name',build,*self.restrictions(row,'bridge' if profile.build_network else 'none'),
            image,'build',profile.model_dump_json())
        self.docker('cp','-',build+':/app',input=archive,timeout=30)
        guard();update(source_digest=digest,started_at=utc_now().isoformat())
        self.docker('start',build)
        deadline=time.monotonic()+profile.timeout_seconds
        while True:
            guard();info=self.resource(row,'container',build)
            if not info: raise PreviewRuntimeError('Build container disappeared.')
            if not info['State']['Running']:
                update(logs=self.logs(row))
                if info['State']['ExitCode']!=0: raise PreviewRuntimeError('Preview dependency preparation/build failed. Inspect preview logs.')
                break
            if time.monotonic()>deadline: raise PreviewRuntimeError('Preview build timed out.')
            time.sleep(.2)
        self.docker('rm',build)
        guard()
        self.docker('network','create','--driver=bridge','--opt','com.docker.network.bridge.enable_icc=false',*self.label_args(row),network)
        container=self.docker('create','--name',run,*self.restrictions(row,network,runtime=True),
            '--publish',f'127.0.0.1::{profile.container_port}',image,'start',profile.model_dump_json())
        guard();update(status='starting',container_id=container)
        self.docker('start',run)
        info=self.resource(row,'container',run)
        bindings=info['NetworkSettings']['Ports'].get(str(profile.container_port)+'/tcp') or []
        if len(bindings)!=1 or bindings[0]['HostIp']!='127.0.0.1': raise PreviewRuntimeError('Unsafe or missing loopback port binding; startup refused.')
        port=int(bindings[0]['HostPort']);update(host_port=port)
        deadline=time.monotonic()+profile.timeout_seconds
        while time.monotonic()<deadline:
            guard();info=self.resource(row,'container',run)
            if not info or not info['State']['Running']: raise PreviewRuntimeError('Preview application exited before becoming healthy.')
            if self.healthy(port,profile.health_path): return dict(host_port=port,container_id=container,source_digest=digest,logs=self.logs(row))
            time.sleep(.3)
        raise PreviewRuntimeError('Preview health check timed out. READY was not reported.')

    def healthy(self,port,path):
        try:
            with self.http.open(f'http://127.0.0.1:{int(port)}{path}',timeout=1) as response:
                return 200<=response.status<300
        except (OSError,urllib.error.URLError): return False

    def logs(self,row):
        lines=[]
        for name in self.names(row)[:2]:
            if self.resource(row,'container',name):
                # Rotation bounds on-disk logs; tail bounds the retained application view.
                try:
                    result=subprocess.run([self.config.docker_executable,'logs','--tail','100',name],capture_output=True,
                        timeout=10,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    lines.append((result.stdout+result.stderr).decode(errors='replace')[-16384:])
                except (OSError,subprocess.TimeoutExpired): lines.append('Logs currently unavailable.')
        return '\n'.join(lines)[-16384:]

    def cleanup(self,row):
        build,run,volume,network=self.names(row)
        for name in (build,run):
            if self.resource(row,'container',name): self.docker('rm','-f',name)
        for kind,name in (('volume',volume),('network',network)):
            if self.resource(row,kind,name): self.docker(kind,'rm',name)

    def owned_containers(self):
        result=self.docker('ps','-a','--filter','label=codeops.workspace='+self.workspace_key,
            '--filter','label=codeops.preview_id','--format','{{.Names}}')
        return result.splitlines() if result else []

    def owned_resources(self,kind):
        result=self.docker(kind,'ls','--filter','label=codeops.workspace='+self.workspace_key,
            '--filter','label=codeops.preview_id','--format','{{.Name}}')
        return result.splitlines() if result else []
