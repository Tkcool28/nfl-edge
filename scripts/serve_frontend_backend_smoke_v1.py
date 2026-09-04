#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import uvicorn
from fastapi.staticfiles import StaticFiles
from nfl_edge.backend.app import create_app
from nfl_edge.backend.settings import BackendSettings
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8770);a=p.parse_args();app=create_app(BackendSettings.from_env());app.mount('/',StaticFiles(directory=ROOT/'frontend',html=True),name='frontend');uvicorn.run(app,host=a.host,port=a.port,log_level='warning');return 0
if __name__=='__main__':raise SystemExit(main())
