export type BomField='material'|'spec'|'quantity'|'unit'|'need_by';
export type BomInput=Record<BomField,string>;
export type BomError={row:number;field:BomField;message:string};
export function positiveQuantity(value:string){if(!/^\d+(\.\d{1,6})?$/.test(value)||!/[1-9]/.test(value))return false;const [whole,fraction='']=value.split('.');return whole.replace(/^0+/,'').length+fraction.length<=18;}
export function validDate(value:string){if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;const date=new Date(value+'T00:00:00Z');return !Number.isNaN(date.valueOf())&&date.toISOString().slice(0,10)===value;}
export function validateBom(lines:BomInput[]):BomError[]{const errors:BomError[]=[];if(!lines.length||lines.length>5000)return[{row:1,field:'material',message:'BOM须有1—5000行'}];for(const [i,l] of lines.entries()){for(const [field,max] of [['material',120],['spec',200],['unit',20]] as const)if(!l[field].trim()||l[field].length>max)errors.push({row:i+1,field,message:'须填写1—'+max+'字'});if(!positiveQuantity(l.quantity))errors.push({row:i+1,field:'quantity',message:'数量须大于0，最多18位有效数字和6位小数'});if(!validDate(l.need_by))errors.push({row:i+1,field:'need_by',message:'请填写有效需用日期'});}return errors;}
