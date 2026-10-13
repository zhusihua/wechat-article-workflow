import io
import json
from pathlib import Path
import zipfile
import pytest
import download_sources as sources
import wechat


def fixture_repo(content=b'original'):
    return {'folder':'example','tree':[{'type':'blob','path':'dir/file.txt','sha':sources.blob_sha(content),'mode':'100644'}]}


def archive(content=b'original'):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('example-sha/dir/file.txt',content)
    return buf.getvalue()


def test_pinned_archive_install_and_verify(tmp_path):
    repo=fixture_repo()
    sources.install_archive(repo,archive(),tmp_path)
    assert sources.verify_repo(repo,tmp_path)==[]
    # Re-running does not rewrite verified files.
    target=tmp_path/'projects/example/dir/file.txt'
    stamp=target.stat().st_mtime_ns
    sources.install_archive(repo,archive(),tmp_path)
    assert target.stat().st_mtime_ns==stamp


def test_changed_upstream_is_never_overwritten(tmp_path):
    repo=fixture_repo()
    sources.install_archive(repo,archive(),tmp_path)
    target=tmp_path/'projects/example/dir/file.txt'
    target.write_bytes(b'local change')
    with pytest.raises(ValueError,match='refusing to overwrite'):
        sources.install_archive(repo,archive(),tmp_path)
    assert target.read_bytes()==b'local change'


def test_corrupt_archive_writes_nothing(tmp_path):
    with pytest.raises(ValueError,match='checksum mismatch'):
        sources.install_archive(fixture_repo(),archive(b'corrupt'),tmp_path)
    assert not (tmp_path/'projects/example').exists()


@pytest.mark.parametrize('path',['../escape','/absolute','a/../../escape','a\\escape'])
def test_archive_path_traversal_rejected(path):
    with pytest.raises(ValueError): sources.safe_relative(path)


def test_doctor_without_machine_config(tmp_path,monkeypatch):
    (tmp_path/'projects').mkdir()
    (tmp_path/'projects/SOURCES.json').write_text('[]')
    monkeypatch.setattr(wechat,'ROOT',tmp_path)
    result=wechat.doctor()
    assert result['node_ready'] is False
    assert result['browser_ready'] is False
    assert result['skill_ready'] is False
