import argparse
import json
import os
from pathlib import Path
import sys
from . import windows
from .adapters import inspect_installation, build_plan
from .resources import SwitchError
from .transaction import Engine, save


def parser():
    p=argparse.ArgumentParser(description='Local Adobe UI language switcher — inspect, preview, apply and restore')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('gui')
    sub.add_parser('discover')
    inspect=sub.add_parser('inspect');inspect.add_argument('root')
    for name in ('plan','apply'):
        item=sub.add_parser(name)
        item.add_argument('root')
        item.add_argument('--target',default='zh_CN')
        item.add_argument('--mode',choices=('native','mapped'),default='native')
        item.add_argument('--carrier',default=None)
        item.add_argument('--carrier-confirmed',action='store_true',help='You have already tested that this carrier locale launches normally')
        if name=='apply':
            item.add_argument('--yes',action='store_true',help='Confirm the previewed changes')
            item.add_argument('--expected-user',help=argparse.SUPPRESS)
            item.add_argument('--receipt',help=argparse.SUPPRESS)
    history=sub.add_parser('history');history.add_argument('--state')
    restore=sub.add_parser('restore');restore.add_argument('transaction');restore.add_argument('--state')
    restore.add_argument('--yes',action='store_true');restore.add_argument('--expected-user',help=argparse.SUPPRESS);restore.add_argument('--receipt',help=argparse.SUPPRESS)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args=parser().parse_args(argv)
    receipt=getattr(args,'receipt',None)
    # GUI receipts are restricted to the application state directory.
    receipt_path=None
    if receipt:
        candidate=Path(receipt).absolute()
        expected=(windows.state_root()/'receipts').resolve()
        if candidate.parent.resolve()!=expected or candidate.suffix!='.json':
            print('Invalid receipt path',file=sys.stderr);return 2
        expected.mkdir(parents=True,exist_ok=True);receipt_path=candidate
    try:
        wanted=getattr(args,'expected_user',None)
        if wanted and windows.user_identity()!=wanted:
            raise SwitchError('Administrator account differs from the requesting Windows account. No changes made.')
        if args.command=='gui':
            from .gui import run
            run();return 0
        if args.command=='discover':
            result=[app.summary() for app in windows.discover()]
        elif args.command=='inspect':
            result=inspect_installation(args.root).summary()
        elif args.command in ('plan','apply'):
            app=inspect_installation(args.root)
            plan=build_plan(app,args.target,args.mode,args.carrier,confirmed=args.carrier_confirmed)
            result=plan.summary()
            if args.command=='apply':
                if not args.yes:
                    raise SwitchError('Preview with plan, then pass --yes to apply')
                transaction=Engine().apply(plan)
                result=dict(status='applied',transaction=transaction,startup='Not tested. Launch manually; restore if startup fails.',warnings=plan.warnings)
        elif args.command=='history':
            result=Engine(args.state).histories()
        else:
            if not args.yes:
                raise SwitchError('Pass --yes to restore the named transaction')
            result=dict(status=Engine(args.state).rollback(args.transaction),transaction=args.transaction)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if receipt_path:
            save(receipt_path,dict(ok=True,result=result))
        return 0
    except (SwitchError,OSError,ValueError,KeyError) as exc:
        result=dict(ok=False,error=str(exc))
        print(json.dumps(result,ensure_ascii=False),file=sys.stderr)
        if receipt_path:
            save(receipt_path,result)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
