"""Organizer-controlled execution: container isolation by default, explicit trusted-local mode."""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .client import Client


def execute(command, timeout, container_name=None):
    started = time.perf_counter()
    try:
        # Discard unbounded participant output; artifacts are collected explicitly.
        completed = subprocess.run(command, timeout=timeout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        measured_ms = (time.perf_counter() - started) * 1000
        if completed.returncode:
            raise ValueError(f'Inference exited with status {completed.returncode}')
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Inference exceeded the task timeout') from exc
    finally:
        if container_name:
            subprocess.run(['docker', 'rm', '-f', container_name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
    return measured_ms


def collect(output):
    files = {}
    for name in ('edited.png', 'mask.png', 'metadata.json'):
        path = output / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError(f'Missing or invalid bounded output artifact: {name}')
        files[name] = path.read_bytes()
    if len(files['metadata.json']) > 16_384:
        raise ValueError('Metadata exceeds 16 KB')
    metadata = json.loads(files['metadata.json'])
    if not isinstance(metadata, dict):
        raise ValueError('metadata.json must contain an object')
    return files, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://127.0.0.1:8000')
    parser.add_argument('--team', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--split', choices=['train', 'validation', 'test'], default='validation')
    parser.add_argument('--profile', required=True)
    parser.add_argument('--timeout', type=float, default=120)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--image', help='Prebuilt Docker image implementing the entry point')
    mode.add_argument('--trusted-local', action='store_true', help='Run only organizer-trusted code without isolation')
    parser.add_argument('--memory', default='8g')
    parser.add_argument('--cpus', type=float, default=2)
    parser.add_argument('--gpus', help='Docker GPU device selection, e.g. device=0')
    parser.add_argument('command', nargs=argparse.REMAINDER, help='Local command with {input} and {output} placeholders')
    args = parser.parse_args()
    if args.timeout <= 0 or args.cpus <= 0:
        parser.error('Timeout and CPU budget must be positive')
    client = Client(args.server)
    config = client.request('/api/config')
    if not config['admin'] or args.profile != config['hardware_profile']:
        parser.error('An organizer token and matching hardware profile are required')
    client.request('/api/runs', {'student_id': args.team, 'run_id': args.run, 'split': args.split, 'mode': 'measured'})
    client.request('/api/select-run', {'student_id': args.team, 'split': args.split, 'run_id': args.run})
    failures = []
    for task in client.request('/api/tasks?split=' + args.split):
        try:
            with tempfile.TemporaryDirectory(prefix='challenge-run-') as tmp:
                root = Path(tmp)
                source, output = root / 'input', root / 'output'
                source.mkdir(mode=0o755)
                output.mkdir(mode=0o777)
                output.chmod(0o777)
                (source / 'source.png').write_bytes(client.request(task['image_url'], binary=True))
                (source / 'task.json').write_text(json.dumps({k: task[k] for k in ('task_id', 'source_prompt', 'target_prompt')} | {'source_image': 'source.png'}))
                name = None
                if args.image:
                    name = 'challenge-' + uuid.uuid4().hex
                    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only',
                               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '128',
                               '--memory', args.memory, '--cpus', str(args.cpus), '--user', '65534:65534',
                               '--tmpfs', '/tmp:rw,noexec,nosuid,size=256m',
                               '--mount', f'type=bind,src={source},dst=/input,readonly',
                               '--mount', f'type=bind,src={output},dst=/output']
                    if args.gpus:
                        command += ['--gpus', args.gpus]
                    command += [args.image, '--input', '/input/task.json', '--output', '/output']
                else:
                    command = args.command
                    if command[:1] == ['--']:
                        command = command[1:]
                    if not command or not any('{input}' in arg for arg in command) or not any('{output}' in arg for arg in command):
                        raise ValueError('Supply a trusted command with {input} and {output} placeholders')
                    command = [arg.replace('{input}', str(source / 'task.json')).replace('{output}', str(output)) for arg in command]
                measured_ms = execute(command, args.timeout, name)
                files, metadata = collect(output)
                metadata.update(run_id=args.run, timing_policy='cold_start_including_process_and_container_overhead',
                                execution_mode='container' if args.image else 'trusted_local')
                result = client.request('/api/measured-submissions', {
                    'task_id': task['task_id'], 'student_id': args.team, 'metadata': metadata,
                    'edited_image': base64.b64encode(files['edited.png']).decode(),
                    'predicted_mask': base64.b64encode(files['mask.png']).decode(),
                    'measured_total_time_ms': measured_ms, 'hardware_profile': args.profile})
                print(json.dumps(result))
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            failures.append(task['task_id'])
            print(f'{task["task_id"]}: {exc}', file=sys.stderr)
    if failures:
        print('Failed tasks count as missing (zero) on the leaderboard: ' + ', '.join(failures), file=sys.stderr)
        sys.exit(1)
    client.request('/api/select-run', {'student_id': args.team, 'split': args.split, 'run_id': args.run})


if __name__ == '__main__':
    main()
