"""Generate a source-only production candidate build; does not deploy or migrate."""
import json,pathlib,shutil,subprocess,sys,os
root=pathlib.Path(__file__).resolve().parents[1]
env={**os.environ,'SECURITY_BUILD_TAG':'production-candidate-2000-3h'}
env.pop('BASE_SECURITY_IMAGE',None)
stage=pathlib.Path(subprocess.check_output([sys.executable,str(root/'scripts/stage_isolated_security_build.py')],env=env,text=True).strip())
shutil.copy2(root/'Dockerfile.production',stage/'Dockerfile.production')
config=json.loads((stage/'cloudbuild.json').read_text())
config['steps'][0]['args'][2]='Dockerfile.production'
# Use the isolated artifact repository and build account; no production resources.
(stage/'cloudbuild.json').write_text(json.dumps(config,indent=2))
print(stage)
