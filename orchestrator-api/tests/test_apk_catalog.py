import asyncio
import hashlib
import io
import os
from pathlib import Path
import sys
import time
import zipfile
from uuid import uuid4

from fastapi import HTTPException, UploadFile
import psycopg
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


@pytest.mark.parametrize('failure,expected',[
    (HTTPException(403,'Actor permission revoked'),403),
    (psycopg.errors.UniqueViolation('Rollback is certain'),503),
    (psycopg.OperationalError('Commit acknowledgement lost'),503),
])
def test_rejected_catalogue_import_removes_only_a_definitely_rolled_back_file(control_client,tmp_path,monkeypatch,failure,expected):
    from app.emulator_store import EmulatorStore
    monkeypatch.setenv('EMULYTIX_APK_ROOT',str(tmp_path))
    monkeypatch.setattr(apk_catalog,'_badging',lambda path:"package: name='com.example.demo' versionCode='1'\n")
    def rejected(*args,**kwargs):
        raise failure
    monkeypatch.setattr(EmulatorStore,'add_application',rejected)
    result = control_client.post('/console/applications',files={'file':('demo.apk',archive_bytes(),'application/vnd.android.package-archive')})
    assert result.status_code==expected
    assert len(list(tmp_path.glob('*.apk')))==(1 if isinstance(failure,psycopg.OperationalError) else 0)
    assert not list(tmp_path.glob('.import-*'))


@pytest.mark.parametrize('changed',['contents','symlink','filename'])
def test_rollback_cleanup_refuses_files_without_the_import_ownership_proof(tmp_path,monkeypatch,changed):
    monkeypatch.setenv('EMULYTIX_APK_ROOT',str(tmp_path))
    app_id = str(uuid4())
    content = b'import-owned-artifact'
    filename = app_id+'.apk'
    target = tmp_path/filename
    target.write_bytes(content)
    metadata = {'id':app_id,'filename':filename,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    if changed=='contents':
        target.write_bytes(b'changed-artifact')
    elif changed=='symlink':
        other = tmp_path/'another-artifact'
        target.rename(other)
        target.symlink_to(other)
    else:
        metadata['filename']='../another-artifact.apk'
    assert not apk_catalog.discard_rejected_import(metadata)
    assert target.exists()


@pytest.mark.parametrize('fault', [None, 'md5', 'signer', 'sdk', 'abi', 'split', 'launcher'])
def test_store_apk_requires_the_exact_signed_compatible_artifact(tmp_path, monkeypatch, fault):
    content = archive_bytes()
    sha1, sha256 = '1' * 40, '2' * 64
    checksum = hashlib.md5(content, usedforsecurity=False).hexdigest() if fault != 'md5' else '3' * 32
    expected = apk_catalog.ExpectedApk('com.example.demo', 1, None, len(content),
                                       md5=checksum, signer_sha1=sha1, signer_sha256=sha256)
    badging = (
        "package: name='com.example.demo' versionCode='1'\n"
        f"sdkVersion:'{34 if fault == 'sdk' else 23}'\n"
        f"native-code: '{'arm64-v8a' if fault == 'abi' else 'x86_64'}'\n"
    )
    if fault != 'launcher':
        badging += "launchable-activity: name='com.example.demo.MainActivity'\n"
    if fault == 'split':
        badging += "uses-split:'required'\n"

    def verify(arguments, *, timeout):
        assert arguments[:3] == ['apksigner', 'verify', '--print-certs']
        assert timeout == 25
        return (f"Signer #1 certificate SHA-1 digest: {sha1}\n"
                f"Signer #1 certificate SHA-256 digest: {'4' * 64 if fault == 'signer' else sha256}\n")

    monkeypatch.setenv('EMULYTIX_APK_ROOT', str(tmp_path))
    monkeypatch.setattr(apk_catalog, '_badging', lambda path: badging)
    monkeypatch.setattr(apk_catalog, '_apk_tool', verify)
    if fault is not None:
        with pytest.raises(HTTPException) as rejected:
            apk_catalog.ingest_apk_chunks([content], expected=expected)
        assert rejected.value.status_code == 422
        assert not list(tmp_path.iterdir())
    else:
        accepted = apk_catalog.ingest_apk_chunks([content], expected=expected)
        assert accepted['sha256'] == hashlib.sha256(content).hexdigest()
        assert (tmp_path / accepted['filename']).read_bytes() == content


@pytest.mark.parametrize(('version_code', 'version_name', 'expected_code', 'accepted'), [
    (" versionCode='76'", '4.8.4', None, True),
    (" versionCode='76'", '4.8.3', None, False),
    ('', '4.8.4', None, False),
    (" versionCode='76'", '4.8.4', 77, False),
])
def test_store_apk_requires_expected_version_name_and_valid_version_code(
    tmp_path, monkeypatch, version_code, version_name, expected_code, accepted,
):
    content = archive_bytes()
    path = tmp_path / 'app.apk'
    path.write_bytes(content)
    monkeypatch.setattr(apk_catalog, '_badging', lambda path: (
        f"package: name='com.aurora.store'{version_code} versionName='{version_name}'\n"
        "application-label:'Aurora Store'\n"
    ))
    expected = apk_catalog.ExpectedApk('com.aurora.store', expected_code, None, len(content),
                                       version_name='4.8.4')
    if accepted:
        assert apk_catalog.inspect_apk(path, expected)[0] == 'com.aurora.store'
    else:
        with pytest.raises(HTTPException) as error:
            apk_catalog.inspect_apk(path, expected)
        assert error.value.status_code == 422
