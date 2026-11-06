"""Local-only backup/restore CLI; full archives contain credential hashes and must stay private."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.data_bundle import backup,restore,HEAD
if __name__=='__main__':
 if len(sys.argv)!=4 or sys.argv[1] not in {'backup','restore'}:raise SystemExit('用法: backend/.venv/bin/python scripts/data_bundle.py backup <运行目录> <新zip> | restore <zip> <全新隔离目录>')
 try:
  result=(backup if sys.argv[1]=='backup' else restore)(sys.argv[2],sys.argv[3]);print(json.dumps({'operation':sys.argv[1],'verified':True,'migration':HEAD,'tables':len(result.get('counts',result.get('database',{}).get('counts',{})))},ensure_ascii=False))
 except Exception as e:raise SystemExit('操作未完成：'+str(e))
