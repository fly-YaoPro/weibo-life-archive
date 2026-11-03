#!/usr/bin/env python3
"""Full, read-only story check; same entry point as check_project --stage story."""
import argparse
import json
from pathlib import Path
from story_preflight import check_story_project


def check_story(root):
    result = check_story_project(root)
    return result['errors'], result['warnings']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = check_story_project(args.root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('Story check: ' + ('PASS' if result['ok'] else 'FAIL'))
        for item in result['errors']: print('- ' + item)
        for item in result['warnings']: print('Warning: ' + item)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
