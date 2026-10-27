"""Report local optional package availability without changing the dependency lock."""
import importlib.metadata as md
import json
import platform
from pathlib import Path
packages=[]
for name in ['torch','transformers','numpy','tokenizers','safetensors','huggingface-hub']:
    try:
        packages.append({'name':name,'installed_version':md.version(name)})
    except md.PackageNotFoundError:
        packages.append({'name':name,'installed_version':None})
result={'python':platform.python_version(),'platform':platform.platform(),'core_dependencies':[], 'optional_packages':packages,'note':'Availability only; not evidence of model execution.'}
Path('output/acceptance').mkdir(parents=True,exist_ok=True)
Path('output/acceptance/environment.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
