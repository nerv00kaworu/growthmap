a=Analysis(['../../scripts/growthmap_mcp.py'],pathex=['../..','../../scripts'],datas=[('../../scripts/growthmap_mcp_schemas.json','.')],hiddenimports=['growthmap_credential'])
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='growthmap-mcp',console=True)
