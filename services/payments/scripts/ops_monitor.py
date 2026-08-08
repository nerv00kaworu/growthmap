#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from growthmap_payments.ops import monitoring_snapshot,read_key_fixture
p=argparse.ArgumentParser(description='Isolated local GrowthMap monitoring snapshot')
p.add_argument('--isolated-root',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--mac-key-file',type=Path,required=True)
a=p.parse_args()
try: result=monitoring_snapshot(a.isolated_root,a.db,a.checkpoint,read_key_fixture(a.isolated_root,a.mac_key_file))
except Exception: result={'schema':'growthmap-local-ops-v1','severity':'critical','exit_code':2,'metrics':{'checkpoint':{'checkpoint':'error','integrity':'error','foreign_keys':'error','migration':'error'}}}
print(json.dumps(result,sort_keys=True,separators=(',',':')));raise SystemExit(result['exit_code'])
