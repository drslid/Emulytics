"""Live display observations use real files, a disposable DB and read-only fake ADB."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import threading
from datetime import datetime, timedelta, timezone
import zlib

import psycopg
import pytest

from app.access import required_permission
from app.live_screen import (
    MAGIC, MAX_FRAME_AGE, ScreenPublisher, ScreenUnavailable,
    capture_android, read_frame, valid_png, write_frame,
)
from app.run_models import DeviceRegistration
from app.run_store import RunStore
from test_authentication import auth_store
from test_user_roles import signed_in


def png(red=0):
    def chunk(name, content):
        return struct.pack('>I', len(content)) + name + content + struct.pack('>I', zlib.crc32(name + content))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes([0, red, 0, 0, 255]))) + chunk(b'IEND', b'')


def register(dsn, device_id='phone', host='host', serial='SerialABC'):
    return RunStore(dsn).register_device(DeviceRegistration(device_id=device_id, host_id=host, serial=serial, kind='physical'))[0]


def frame_path(root, device_id='phone'):
    return root / 'screens' / (hashlib.sha256(device_id.encode()).hexdigest() + '.frame')


def request_frame(dsn, device_id='phone', seconds=15):
    with psycopg.connect(dsn) as connection:
        connection.execute("INSERT INTO live_screen_requests(device_id,expires_at) VALUES(%s,clock_timestamp()+%s*interval '1 second') ON CONFLICT(device_id) DO UPDATE SET expires_at=EXCLUDED.expires_at", (device_id, seconds))


def test_atomic_packet_returns_current_image_and_unique_observation(tmp_path):
    now = datetime.now(timezone.utc)
    first = write_frame(tmp_path, 'phone', png(), captured_at=now)
    image, metadata, age = read_frame(tmp_path, 'phone', now=now + timedelta(seconds=1))
    assert image == png() and metadata == first and age == 1
    second = write_frame(tmp_path, 'phone', png(255), captured_at=now)
    assert second['frame_id'] != first['frame_id']
    assert read_frame(tmp_path, 'phone', now=now)[0] == png(255)
    assert not list((tmp_path / 'screens').glob('.*'))


@pytest.mark.parametrize('seconds', [MAX_FRAME_AGE + .01, -2])
def test_stale_or_future_frame_never_looks_live(tmp_path, seconds):
    now = datetime.now(timezone.utc)
    write_frame(tmp_path, 'phone', png(), captured_at=now - timedelta(seconds=seconds))
    with pytest.raises(ScreenUnavailable):
        read_frame(tmp_path, 'phone', now=now)


@pytest.mark.parametrize('failure', ['image-checksum', 'header-device', 'header-time', 'header-type', 'invalid-json', 'truncated', 'invalid-png'])
def test_corrupt_or_wrong_device_packet_is_rejected(tmp_path, failure):
    write_frame(tmp_path, 'phone', png())
    target = frame_path(tmp_path)
    header, _, image = target.read_bytes()[len(MAGIC):].partition(b'\n')
    data = json.loads(header)
    if failure == 'image-checksum':
        image = png(255)
    elif failure == 'header-device':
        data['device_id'] = 'another-phone'
    elif failure == 'header-time':
        data['captured_at'] = 'invalid date'
    elif failure == 'header-type':
        data = []
    elif failure == 'invalid-json':
        target.write_bytes(MAGIC + b'{wrong\n' + image)
    elif failure == 'truncated':
        target.write_bytes(MAGIC + b'{}')
    elif failure == 'invalid-png':
        image = b'not an image'
    if failure not in {'invalid-json', 'truncated'}:
        target.write_bytes(MAGIC + json.dumps(data).encode() + b'\n' + image)
    with pytest.raises(ScreenUnavailable):
        read_frame(tmp_path, 'phone')


def test_screen_files_and_directory_cannot_be_symlinked(tmp_path):
    root, elsewhere = tmp_path / 'root', tmp_path / 'elsewhere'
    root.mkdir(); elsewhere.mkdir()
    write_frame(elsewhere, 'phone', png())
    (root / 'screens').symlink_to(elsewhere / 'screens', target_is_directory=True)
    with pytest.raises(ScreenUnavailable):
        read_frame(root, 'phone')
    (root / 'screens').unlink(); (root / 'screens').mkdir()
    frame_path(root).symlink_to(frame_path(elsewhere))
    with pytest.raises(OSError):
        read_frame(root, 'phone')
    with pytest.raises(ScreenUnavailable):
        write_frame(root, 'phone', png())
    with pytest.raises(ScreenUnavailable):
        write_frame(root, '../phone', png())


def test_capture_executes_only_screencap_for_the_exact_serial(tmp_path):
    executable, counter = tmp_path / 'fake-adb', tmp_path / 'count'
    executable.write_text(f'''#!{sys.executable}
import sys
from pathlib import Path
assert sys.argv[1:] == ['-s','SerialABC','exec-out','screencap','-p']
counter=Path({str(counter)!r})
count=int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count+1))
sys.stdout.buffer.write(bytes.fromhex([{png().hex()!r},{png(255).hex()!r}][count % 2]))
''')
    executable.chmod(0o700)
    assert capture_android('SerialABC', adb_binary=str(executable)) == png()
    assert capture_android('SerialABC', adb_binary=str(executable)) == png(255)
    with pytest.raises(ScreenUnavailable):
        capture_android('SerialABC; touch unwanted', adb_binary=str(executable))
    assert counter.read_text() == '2'


def test_publisher_is_on_demand_host_bound_and_stops_after_expiry(database_dsn, tmp_path):
    register(database_dsn)
    register(database_dsn, 'other', 'other-host', 'OtherSerial')
    calls = []
    def capture(serial):
        calls.append(serial)
        return png(len(calls))
    publisher = ScreenPublisher(database_dsn, 'host', tmp_path, tmp_path / 'locks', capture=capture)
    assert publisher.publish_once() == 0 and calls == []
    request_frame(database_dsn); request_frame(database_dsn, 'other')
    assert publisher.publish_once() == 1 and calls == ['SerialABC']
    first = read_frame(tmp_path, 'phone')[1]['frame_id']
    assert publisher.publish_once() == 1
    assert read_frame(tmp_path, 'phone')[1]['frame_id'] != first
    request_frame(database_dsn, seconds=-1)
    assert publisher.publish_once() == 0 and calls == ['SerialABC', 'SerialABC']
    assert not frame_path(tmp_path, 'other').exists()
    stopped = threading.Event(); stopped.set()
    request_frame(database_dsn)
    assert publisher.publish_once(stopped) == 0


def test_api_demands_first_frame_then_delivers_atomic_png_without_caching(control_client, database_dsn, tmp_path, monkeypatch):
    register(database_dsn)
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT', str(tmp_path))
    route = '/console/devices/phone/screen'
    warm = control_client.get(route)
    assert warm.status_code == 503
    with psycopg.connect(database_dsn) as connection:
        assert connection.execute('SELECT COUNT(*) FROM live_screen_requests').fetchone()[0] == 1
    metadata = write_frame(tmp_path, 'phone', png())
    result = control_client.get(route)
    assert result.status_code == 200 and result.content == png()
    assert result.headers['content-type'] == 'image/png'
    assert 'no-store' in result.headers['cache-control']
    assert result.headers['x-screen-captured-at'] == metadata['captured_at']
    assert result.headers['x-screen-frame-id'] == metadata['frame_id']
    assert float(result.headers['x-screen-age']) <= MAX_FRAME_AGE
    assert control_client.get('/console/devices/unknown/screen').status_code == 404
    write_frame(tmp_path, 'phone', png(), captured_at=datetime.now(timezone.utc) - timedelta(seconds=4))
    assert control_client.get(route).status_code == 503


def test_demand_refresh_is_bounded_and_does_not_rewrite_every_poll(control_client, database_dsn, tmp_path, monkeypatch):
    register(database_dsn)
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT', str(tmp_path))
    route = '/console/devices/phone/screen'
    control_client.get(route)
    with psycopg.connect(database_dsn) as connection:
        expiry = connection.execute('SELECT expires_at FROM live_screen_requests').fetchone()[0]
    control_client.get(route)
    with psycopg.connect(database_dsn) as connection:
        assert connection.execute('SELECT expires_at FROM live_screen_requests').fetchone()[0] == expiry
        connection.execute("UPDATE live_screen_requests SET expires_at=clock_timestamp()+interval '1 second'")
    control_client.get(route)
    with psycopg.connect(database_dsn) as connection:
        assert connection.execute('SELECT expires_at FROM live_screen_requests').fetchone()[0] > expiry


def test_display_requires_current_authenticated_read_permission(auth_store, app_module, tmp_path, monkeypatch):
    register(auth_store.config.dsn)
    monkeypatch.setenv('EMULYTIX_ARTIFACT_ROOT', str(tmp_path))
    user, viewer, _ = signed_in(auth_store, app_module, 'viewer')
    write_frame(tmp_path, 'phone', png())
    route = '/console/devices/phone/screen'
    assert required_permission('GET', route) == 'devices.read'
    assert required_permission('POST', route) is None
    assert viewer.get(route).status_code == 200
    with auth_store.connect() as connection:
        connection.execute('DELETE FROM auth_sessions WHERE user_id=%s', (user['id'],))
    assert viewer.get(route).status_code == 401
    assert viewer.get('/console/devices/unknown/screen').status_code == 401


def test_capture_has_a_hard_output_limit_before_reading_unbounded_android_output(tmp_path):
    executable, completed = tmp_path / 'fake-large-adb', tmp_path / 'completed'
    executable.write_text(f"""#!{sys.executable}
import os
from pathlib import Path
for _ in range(32):
 os.write(1,b'x'*1024*1024)
Path({str(completed)!r}).touch()
""")
    executable.chmod(0o700)
    with pytest.raises(ScreenUnavailable):
        capture_android('SerialABC', adb_binary=str(executable))
    assert not completed.exists(), 'oversized producer must be stopped before consuming the whole stream'


def test_publisher_timestamps_capture_start_instead_of_making_a_slow_image_new(database_dsn, tmp_path, monkeypatch):
    import app.live_screen as module
    now = datetime.now(timezone.utc)
    class Clock(datetime):
        current = None
        @classmethod
        def now(cls, _zone):
            return cls.current
    Clock.current = now
    monkeypatch.setattr(module, 'datetime', Clock)
    register(database_dsn)
    request_frame(database_dsn)
    def slow_capture(_serial):
        Clock.current = now + timedelta(seconds=2)
        return png()
    publisher = ScreenPublisher(database_dsn, 'host', tmp_path, tmp_path / 'locks', capture=slow_capture)
    assert publisher.publish_once() == 1
    _image, metadata, age = read_frame(tmp_path, 'phone', now=Clock.current)
    assert metadata['captured_at'] == now.isoformat() and age == 2
