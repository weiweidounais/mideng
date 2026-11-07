const roles=['市场','商务','设计','采购','项目经理','工厂','现场','质量','财务','管理员'];
export function businessRoles(assigned:string[]){return assigned.includes('管理员')?roles:assigned;}
export function hasBusinessRole(assigned:string[],role:string){return businessRoles(assigned).includes(role);}
export function canActFor(roles:string[],actor:string,assigned:string|undefined){return roles.includes('管理员')||actor===assigned;}
