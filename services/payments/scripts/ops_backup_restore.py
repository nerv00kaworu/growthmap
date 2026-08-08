#!/usr/bin/env python3
"""Create an authenticated isolated local DB/checkpoint backup bundle."""
import argparse,json
from pathlib import Path
from growthmap_payments.ops import backup_pair,read_key_fixture
p=argparse.ArgumentParser(description='Create an atomic isolated local payment DB/checkpoint backup pair')
p.add_argument('--isolated-root',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--mac-key-file',type=Path,required=True)
a=p.parse_args();print(json.dumps(backup_pair(a.isolated_root,a.db,a.checkpoint,a.destination,read_key_fixture(a.isolated_root,a.mac_key_file)),sort_keys=True,separators=(',',':')))
