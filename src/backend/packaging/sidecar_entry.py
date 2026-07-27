import os, sys
from pathlib import Path
if not getattr(sys, 'frozen', False): sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    if os.getenv('GROWTHMAP_DESKTOP_MODE') != '1': raise SystemExit('desktop mode required')
    if len(sys.argv) > 1:
        from desktop.database_maintenance import main as maintenance_main
        maintenance_main(sys.argv)
    else:
        import uvicorn
        from main import app
        uvicorn.run(app, host='127.0.0.1', port=int(os.environ['GROWTHMAP_PORT']), access_log=False)
