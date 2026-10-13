"""Synthetic pipeline test; fixture images are not publishable article covers."""
from argparse import Namespace
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'workflow'))
import wechat
from PIL import Image
import yaml

original_root = wechat.ROOT
with tempfile.TemporaryDirectory(prefix='wechat-smoke-') as folder:
    root = Path(folder)
    (root/'workflow').mkdir()
    for name in ['preferences.yaml','preview-template.html','runtime.json','render_mermaid.mjs']:
        shutil.copy2(original_root/'workflow'/name,root/'workflow'/name)
    # Mermaid script resolves its library adjacent to itself.
    (root/'workflow/node_modules').symlink_to(original_root/'workflow/node_modules',target_is_directory=True)
    wechat.ROOT=root
    wechat.new_run(Namespace(topic='流程测试',input=None,title=None))
    run=next((root/'articles').iterdir())
    final='# 流程测试\n\n这是安装验证用合成材料，不是正式文章。\n\n```mermaid\nflowchart TD\n A[输入] --> B[输出]\n```\n'
    for name in ['draft.md','humanized.md','final.md']:
        (run/name).write_text(final,encoding='utf-8')
    assessment={'decision':'pass','pass_number':1,'reviewed_sha256':wechat.sha(run/'final.md'),
                'dimensions':{k:4 for k in ['accuracy','viewpoint','usefulness','voice','readability']},
                'blockers':[],'major_issues':[],'notes':'Synthetic fixture; no factual or artistic validation'}
    (run/'assessment.yaml').write_text(yaml.safe_dump(assessment),encoding='utf-8')
    for name,size in [('cover.png',(235,100)),('cover-square.png',(100,100))]:
        Image.new('RGB',size,'white').save(run/'assets'/name)
    result=wechat.render_run(run)
    assert result['ready'] and len(result['images'])==1
    with zipfile.ZipFile(run/'publish.zip') as z:
        assert {'assets/cover.png','assets/cover-square.png','article.md','preview.html'} <= set(z.namelist())
    assert 'data:image/png;base64,' in (run/'preview.html').read_text()
    runtime=json.loads((original_root/'workflow/runtime.json').read_text())
    subprocess.run([runtime['node'],str(original_root/'workflow/check_preview.mjs'),str(run)],check=True)
    print(json.dumps({'ready':True,'mermaid_png':True,'dual_covers_in_zip':True,'synthetic_only':True}))
