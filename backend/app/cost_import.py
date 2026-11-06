"""Bounded deterministic parsing; never executes Excel formulas or macros."""
import csv,io,zipfile
from datetime import datetime,date
from pathlib import Path
from .pilot_service import fail
FIELDS={'source_id':'源明细ID','line_version':'行版本','project_code':'项目编码','entry_date':'凭证日期','subject_code':'原科目','wbs_code':'原WBS','kind':'类型','business_id':'事项编码','amount':'金额','quantity':'数量','unit':'单位','currency':'币种','tax_basis':'税口径','document_no':'凭证号','document_line':'凭证行号','related_source':'关联源系统','related_period':'关联期间','related_id':'关联源ID','related_version':'关联行版本','note':'说明'}
REQUIRED={'line_version','project_code','entry_date','subject_code','wbs_code','kind','business_id','amount','quantity','unit','currency','tax_basis'}
KINDS={'实际':'actual','暂估':'estimate','承诺':'commitment','付款':'payment','发票':'invoice','待分摊':'unallocated','冲正':'reversal'}

def parse(data,name):
 if Path(name).suffix.lower()=='.csv':
  try:grid=list(csv.reader(io.StringIO(data.decode('utf-8-sig'),newline='')))
  except (UnicodeError,csv.Error):fail(422,'CSV_INVALID','CSV须为有效UTF-8格式')
  formulas=[]
 elif Path(name).suffix.lower()=='.xlsx':
  try:
   with zipfile.ZipFile(io.BytesIO(data)) as z:
    if 'xl/workbook.xml' not in z.namelist() or any('vba' in n.lower() for n in z.namelist()) or len(z.infolist())>2000 or sum(x.file_size for x in z.infolist())>100*1024*1024 or any(x.flag_bits&1 for x in z.infolist()) or z.testzip() is not None:raise ValueError()
   import openpyxl
   book=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
   try:
    if len(book.worksheets)!=1:raise ValueError()
    sheet=book.worksheets[0];grid=[];formulas=[]
    for i,row in enumerate(sheet.iter_rows()):
     if i>5000:fail(422,'ROW_LIMIT','单批最多5000行，请拆批')
     if len(row)>40:fail(422,'COLUMN_LIMIT','最多40列')
     formulas.append([j for j,c in enumerate(row) if c.data_type=='f'])
     grid.append([c.value for c in row])
   finally:book.close()
  except Exception as e:
   if hasattr(e,'detail'):raise
   fail(422,'XLSX_INVALID','须提供单工作表、无宏的有效xlsx文件')
 else:fail(422,'FILE_TYPE','仅支持xlsx与UTF-8 csv')
 if not grid:fail(422,'EMPTY_FILE','源表为空')
 headers=[str(x or '').strip() for x in grid[0]]
 if not headers or len(headers)>40 or any(not h or len(h)>120 for h in headers) or len(set(headers))!=len(headers) or (formulas and formulas[0]):fail(422,'HEADERS_INVALID','列名须非空、唯一且不能为公式')
 rows=[]
 for i,values in enumerate(grid[1:],2):
  if not any(v is not None and str(v).strip() for v in values):continue
  if len(rows)>=5000:fail(422,'ROW_LIMIT','单批最多5000行，请拆批')
  if len(values)>len(headers):fail(422,'COLUMN_COUNT','第'+str(i)+'行列数超过表头')
  def cell(v):return v.isoformat() if isinstance(v,(date,datetime)) else '' if v is None else str(v).strip()
  mapped={h:cell(values[j]) if j<len(values) else '' for j,h in enumerate(headers)}
  formula_headers=[headers[j] for j in (formulas[i-1] if formulas else []) if j<len(headers)]
  formula_headers+= [h for h,v in mapped.items() if v.startswith('=')]
  rows.append({'row':i,'values':mapped,'formulas':sorted(set(formula_headers))})
 if not rows:fail(422,'EMPTY_ROWS','至少提供一条源明细，空表不当作零成本')
 return headers,rows
