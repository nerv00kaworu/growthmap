#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from growthmap_payments.ops import reconciliation_report,read_key_fixture
p=argparse.ArgumentParser(description='Read-only isolated local GrowthMap reconciliation report');p.add_argument('--isolated-root',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--mac-key-file',type=Path,required=True);p.add_argument('--limit',type=int,default=100)
a=p.parse_args();print(json.dumps(reconciliation_report(a.isolated_root,a.db,a.checkpoint,read_key_fixture(a.isolated_root,a.mac_key_file),a.limit),sort_keys=True,separators=(',',':')))
