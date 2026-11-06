import asyncio
import io
import os
from pathlib import Path
import sys
import time
import zipfile

from fastapi import HTTPException, UploadFile
import pytest

from app import apk_catalog


def archive_bytes(manifest=True):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('AndroidManifest.xml' if manifest else 'wrong.xml', b'binary-manifest')
    return data.getvalue()


def test_apk_import_uses_generated_immutable_name_and_manifest_package(tmp_path, monkeypatch):
    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    monkeypatch.setattr(apk_catalog, '_badging', lambda path:
        "package: name='com.example.demo' versionCode='1'\napplication-label:'Example'\n")
    content = archive_bytes()
    file = UploadFile(io.BytesIO(content), filename='../../outside.apk')
    result = asyncio.run(apk_catalog.ingest_apk(file))
    assert result['package_name'] == 'com.example.demo'
    assert result['name'] == 'Example'
    assert (tmp_path / result['filename']).read_bytes() == content
    assert Path(result['filename']).name == result['filename']
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('content', [b'not-a-zip', archive_bytes(False)])
def test_invalid_apk_never_remains_in_catalog_directory(tmp_path, monkeypatch, content):
    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    with pytest.raises(HTTPException) as failure:
        asyncio.run(apk_catalog.ingest_apk(UploadFile(io.BytesIO(content), filename='x.apk')))
    assert failure.value.status_code == 422
    assert not list(tmp_path.iterdir())


def test_oversized_apk_is_stopped_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    monkeypatch.setattr(apk_catalog, 'MAX_APK_BYTES', 10)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(apk_catalog.ingest_apk(UploadFile(io.BytesIO(b'x' * 11), filename='x.apk')))
    assert failure.value.status_code == 413
    assert not list(tmp_path.iterdir())


def test_split_apk_is_rejected_before_publication(tmp_path, monkeypatch):
    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    monkeypatch.setattr(apk_catalog, '_badging', lambda path:
        "package: name='com.example.demo' versionCode='1' split='config.x86'\n")
    with pytest.raises(HTTPException) as failure:
        asyncio.run(apk_catalog.ingest_apk(UploadFile(io.BytesIO(archive_bytes()), filename='x.apk')))
    assert failure.value.status_code == 422
    assert not list(tmp_path.iterdir())


def test_manifest_inspector_output_is_bounded_while_the_process_runs(tmp_path, monkeypatch):
    binary = tmp_path / 'aapt'
    binary.write_text(f'#!{sys.executable}\nimport os,time\nos.write(1,b"x"*2097152)\ntime.sleep(30)\n')
    binary.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ.get('PATH', ''))
    started = time.monotonic()
    with pytest.raises(ValueError, match='exceeds'):
        apk_catalog._badging(tmp_path / 'unused.apk')
    assert time.monotonic() - started < 5
