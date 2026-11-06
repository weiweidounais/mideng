import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.legacy_rehearsal import rehearse
if __name__=='__main__':
 if len(sys.argv)!=3:raise SystemExit('用法: backend/.venv/bin/python scripts/migration_rehearsal.py <合成或脱敏旧结构JSON> <新隔离目录>')
 report=rehearse(sys.argv[1],sys.argv[2]);print(json.dumps({k:report[k] for k in ['source_packages','proposals','demonstration_excluded','originals_verified','missing_originals','unverified_authors','business_activated']},ensure_ascii=False))
