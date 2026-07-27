import os, uvicorn
from main import app
if __name__ == '__main__':
    if os.getenv('GROWTHMAP_DESKTOP_MODE') != '1': raise SystemExit('desktop mode required')
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['GROWTHMAP_PORT']), access_log=False)
