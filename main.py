"""Start the medical education workbench from the repository root."""
import argparse
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MediGraphRAG 医学知识与出题平台')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true')
    options = parser.parse_args()
    uvicorn.run('web.api.main:app', host=options.host, port=options.port, reload=options.reload)
