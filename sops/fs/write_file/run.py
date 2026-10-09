import json, hashlib, os, sys


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    try:
        args = json.load(sys.stdin)
    except Exception as exc:
        sys.stderr.write('invalid JSON input: %s' % str(exc))
        sys.exit(1)

    filename = args.get('filename')
    content = args.get('content')
    mkdir = bool(args.get('mkdir', True))
    allow_overwrite = bool(args.get('allow_overwrite', False))

    if not isinstance(filename, str) or not filename:
        sys.stderr.write('filename must be a non-empty string')
        sys.exit(1)
    if not isinstance(content, str):
        sys.stderr.write('content must be a string')
        sys.exit(1)

    parts = filename.replace('\\', '/').split('/')
    if any(p == '..' for p in parts):
        sys.stderr.write('filename may not traverse outside the current directory')
        sys.exit(1)

    target = os.path.join(os.getcwd(), *parts)
    target_dir = os.path.dirname(target)

    try:
        if mkdir:
            os.makedirs(target_dir, exist_ok=True)
        if os.path.exists(target) and os.path.isfile(target) and not allow_overwrite:
            sys.stderr.write('refusing to overwrite existing file: %s' % target)
            sys.exit(1)
        data = content.encode('utf-8')
        with open(target, 'wb') as f:
            f.write(data)
        sys.stdout.write(json.dumps({
            'ok': True,
            'path': os.path.abspath(target),
            'bytes_written': len(data),
            'sha256': _sha256(data),
        }))
    except Exception as exc:
        sys.stderr.write('failed to write file: %s' % str(exc))
        sys.exit(1)


if __name__ == '__main__':
    main()