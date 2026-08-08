#!/usr/bin/env python3
"""Restore is a library operation requiring an isolated fixture Config.

Call growthmap_payments.ops.restore_pair(..., expected_bundle_digest=...) from an
isolated drill which constructs its generated fixture Config. There is intentionally
no environment-derived production composition in this CLI surface.
"""
import argparse
p=argparse.ArgumentParser(description='Restore requires fixture Config via the Python API')
p.add_argument('--expected-bundle-digest',required=True)
p.parse_args();raise SystemExit('Use restore_pair with isolated fixture Config; anti-replay beyond caller-selected digest is NOT PROVIDED')
