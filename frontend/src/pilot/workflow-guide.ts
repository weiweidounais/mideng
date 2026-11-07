export const businessFlow=[
 {title:'录入需求',role:'市场 / 商务',action:'新建需求，填写标题、正文和来源，保存草稿。'},
 {title:'发布正式需求',role:'商务',action:'核对需求，选择设计接收人，发布正式需求。'},
 {title:'编制并发布方案',role:'设计',action:'只编制可落地的实施方案与附件，选择项目经理接收人并发布。'},
 {title:'提出采购需求',role:'项目经理',action:'根据正式落地方案填写采购物品种类、规格、数量、单位和需用日期，再提交采购需求。'},
 {title:'执行采购',role:'采购',action:'接采购需求，登记供应商、订购数量和约定到货时间。'},
 {title:'复核订购结果',role:'项目经理',action:'核对订购数量与约定到货时间，确认后交质量等待到货。'},
 {title:'到货与质量验收',role:'质量',action:'登记实际到货，上传验收证据，确认材料合格。'},
 {title:'合同与成本归档',role:'商务',action:'记录采购合同、合同金额和成本明细，确认归档。'},
] as const;
export function canCreateRequirement(roles:string[]){return roles.some(role=>role==='市场'||role==='商务'||role==='管理员');}
type FlowDoc={has_draft:boolean;needs_review?:boolean;versions:{current:boolean}[]};
export function requirementNextStep(requirement:FlowDoc,schemes:FlowDoc[]):'publish-requirement'|'review-requirement'|'create-scheme'|'review-scheme'|'publish-scheme'|'procurement'{
 if(requirement.has_draft)return 'publish-requirement';
 if(!requirement.versions[0]?.current)return 'review-requirement';
 if(schemes.some(scheme=>scheme.needs_review))return 'review-scheme';
 if(schemes.some(scheme=>scheme.has_draft))return 'publish-scheme';
 if(schemes.some(scheme=>scheme.versions[0]?.current))return 'procurement';
 return 'create-scheme';
}
