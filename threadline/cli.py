"""Command line interface for visual and structured source review."""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .changes import review_changes
from .server import make_server
from .service import SnapshotStore, ThreadlineError


def main(argv=None, default_command=None):
    values=list(sys.argv[1:] if argv is None else argv)
    commands={'review','inspect','changes'}
    if default_command and (not values or values[0] not in commands): values.insert(0,default_command)
    parser=argparse.ArgumentParser(prog='threadline', description='Review Python source without importing or running the target.')
    sub=parser.add_subparsers(dest='command',required=True)
    review=sub.add_parser('review');review.add_argument('project');review.add_argument('--port',type=int,default=4173);review.add_argument('--no-open',action='store_true');review.add_argument('--source-root',action='append');review.add_argument('--exclude',action='append');review.add_argument('--file',action='append',dest='change_files');review.add_argument('--base',help='show Python changes against this Git revision')
    inspect=sub.add_parser('inspect');inspect.add_argument('project');inspect.add_argument('--source-root',action='append');inspect.add_argument('--exclude',action='append');inspect.add_argument('--entrypoint');inspect.add_argument('--query',default='');inspect.add_argument('--cursor',type=int,default=0);inspect.add_argument('--limit',type=int,default=25);inspect.add_argument('--format',choices=['json'],default='json')
    changes=sub.add_parser('changes');changes.add_argument('project');changes.add_argument('--base',default='HEAD');changes.add_argument('--file',action='append',dest='change_files');changes.add_argument('--format',choices=['json'],default='json')
    args=parser.parse_args(values)
    try:
        if args.command=='review':
            server=make_server(args.project,port=args.port,base=args.base,source_roots=args.source_root,exclude=args.exclude,change_files=args.change_files);url=f'http://127.0.0.1:{server.server_address[1]}/'
            print(f'Threadline is reviewing {Path(args.project).resolve()}\nOpen {url}',flush=True)
            if not args.no_open:webbrowser.open(url)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:server.server_close()
        elif args.command=='inspect':
            store=SnapshotStore(args.project,source_roots=args.source_root,exclude=args.exclude);summary=store.summary(limit=args.limit)
            if args.entrypoint:
                symbol=_resolve(store.current,args.entrypoint);result=store.get_workflow(symbol['id'],cursor=args.cursor,limit=args.limit)
            else:result=store.find_symbols(args.query,cursor=args.cursor,limit=args.limit)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.command=='changes': print(json.dumps(review_changes(args.project,args.base,args.change_files),ensure_ascii=False,indent=2))
    except ThreadlineError as exc:
        parser.error(str(exc))

def _resolve(model, selector):
    choices=[s for s in model['scopes'].values() if selector in (s['id'],s['qualified'],f"{s['module']}:{s['qualified']}",f"{s['module']}:{s['name']}")]
    if len(choices)!=1: raise ThreadlineError(f"entrypoint must identify exactly one symbol; found {len(choices)} for {selector!r}")
    return choices[0]
