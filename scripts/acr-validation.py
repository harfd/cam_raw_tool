"""Prepare reproducible ACR test cases or compare an actual Adobe export."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.raw_decoder import decode
from backend.models import RenderRequest,WhiteBalance
from backend.parameter_engine import build_recipe
from backend.xmp import template_info
from backend import acr_validation as acr


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('prepare')
    prepare.add_argument('--source',type=Path,required=True)
    prepare.add_argument('--template',type=Path,required=True)
    prepare.add_argument('--output',type=Path,required=True)
    compare=sub.add_parser('compare')
    compare.add_argument('--snapshot',type=Path,required=True)
    compare.add_argument('--image',type=Path,required=True)
    compare.add_argument('--acr-version',required=True)
    compare.add_argument('--camera-profile',required=True)
    compare.add_argument('--assume-srgb',action='store_true')
    args=parser.parse_args()
    if args.command=='compare':
        report=acr.compare(args.snapshot,args.image.read_bytes(),args.assume_srgb,args.acr_version,args.camera_profile)
        print(json.dumps(report,ensure_ascii=False,indent=2));return
    # A unique run directory avoids replacing earlier Adobe exports or references.
    directory=args.output.resolve()/uuid4().hex
    directory.mkdir(parents=True)
    shutil.copy2(args.source,directory/'source.NEF')
    _,metrics,_=decode(directory/'source.NEF',directory)
    template=template_info(args.template)
    metrics['white_balance_reference']=template.get('white_balance_reference',{'temperature':5500,'tint':0,'source':'估计参考值','estimated':True})
    job={'id':uuid4().hex,'metrics':metrics,'template':template,'regions':[]}
    neutral={'Exposure2012':0,'Highlights2012':0,'Shadows2012':0,'Whites2012':0}
    cases={
      '01-neutral':RenderRequest(strength=0,use_ai=False,overrides=neutral,white_balance=WhiteBalance(mode='as_shot')),
      '02-exposure':RenderRequest(strength=0,use_ai=False,overrides={**neutral,'Exposure2012':.5},white_balance=WhiteBalance(mode='as_shot')),
      '03-curve':RenderRequest(strength=0,use_ai=False,overrides=neutral,white_balance=WhiteBalance(mode='as_shot'),curve_overrides={'rgb':[{'x':0,'y':0},{'x':64,'y':56},{'x':128,'y':128},{'x':192,'y':202},{'x':255,'y':255}]}),
      '04-color':RenderRequest(strength=0,use_ai=False,white_balance=WhiteBalance(mode='as_shot'),overrides={**neutral,'SaturationAdjustmentGreen':-20,'LuminanceAdjustmentOrange':10,'ColorGradeMidtoneHue':40,'ColorGradeMidtoneSat':10}),
    }
    results=[]
    for name,state in cases.items():
        record=acr.create(job,state,build_recipe(metrics,None,state),directory)
        root=directory/'validation'/record['id']
        shutil.copy2(root/'package.zip',directory/(name+'.zip'))
        results.append({'case':name,'snapshot':str(root),'package':str(directory/(name+'.zip')),'settings':state.model_dump()})
    (directory/'cases.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(directory/'cases.json'))


if __name__=='__main__':main()
