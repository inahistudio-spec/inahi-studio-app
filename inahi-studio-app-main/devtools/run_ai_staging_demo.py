"""Disposable local UI for Phase 7. Never uses a key, PostgreSQL or ambient data."""
import argparse
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=5057)
    parser.add_argument('--stop-on-stdin',action='store_true',help='Close the disposable server when its parent closes stdin')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error('Puerto local no válido')
    with tempfile.TemporaryDirectory(prefix='inahi-ai-synthetic-') as directory:
        from sqlalchemy.engine import URL
        path=Path(directory)/'synthetic.sqlite'
        env={'APP_ENV':'development','DATABASE_URL':URL.create('sqlite',database=str(path)).render_as_string(hide_password=False),
             'DATABASE_PATH':str(path),'SECRET_KEY':secrets.token_hex(32),'COPILOT_PROVIDER':'local','COPILOT_EXTERNAL_ENABLED':'false',
             'COPILOT_ALLOW_EXTERNAL':'false','COPILOT_REQUESTS_PER_MINUTE':'30','FLASK_SKIP_DOTENV':'1'}
        with patch.dict(os.environ,env,clear=True),patch('socket.socket.connect',side_effect=OSError('Demo: outgoing connections disabled')):
            from persistence.migrations import migrate
            migrate(Path(directory)/'preflight.json',ai_staging=True)
            from evaluations.dataset import seed
            import app
            from contextlib import closing
            password='Synthetic-evaluation-password-123'
            with closing(app.conectar()) as c,c:
                seed(c,password)
            from devtools.run_workspace_demo import ExclusiveDemoServer
            app.app.config.update(SAAS_DEMO=True,SESSION_COOKIE_NAME=f'inahi_ai_demo_{args.port}')
            with ExclusiveDemoServer('127.0.0.1',args.port,app.app) as server:
                if args.stop_on_stdin:
                    def stop_when_parent_finishes():
                        sys.stdin.read()
                        server.shutdown()
                    threading.Thread(target=stop_when_parent_finishes,daemon=True).start()
                print(f'LOCAL SYNTHETIC DEMO: http://127.0.0.1:{args.port}/saas/copilot',flush=True)
                print(f'Only disposable demo: eval-a@example.invalid / {password}',flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass


if __name__=='__main__':
    main()
