export type RuleCase={input:string;expectContains:string|null;expectStatus:'success'|'failed'};
export type RuleStep={node_id:string;label:string;status:'success'|'failed'|'skipped';output_preview:string;truncated:boolean;error:string|null};
export type Evaluation={id:string;purpose:'evaluation';application_id:string;application_revision:number;definition_sha256:string;passed:number;total:number;pass_rate:number;created_at:string;model_enabled:false;cases:(RuleCase&{number:number;actual_status:'success'|'failed';output_preview:string;truncated:boolean;passed:boolean;steps:RuleStep[]})[]};
export type RuleExecution={id:string;purpose?:undefined;applicationId:string;application_revision:number;mode:'draft'|'published';status:string;output:string;createdAt:string;steps:{nodeId:string;label:string;status:string;output?:string;error?:string}[]};
export type RuleHistory=Evaluation|RuleExecution;
export function normalizedCases(cases:RuleCase[]):RuleCase[]{return cases.map(c=>({input:c.input.trim(),expectContains:c.expectContains?.trim()||null,expectStatus:c.expectStatus}));}
export function canPublishEvaluation(report:Evaluation|null,application:{id:string;revision:number},cases:RuleCase[]){
 return !!report&&report.application_id===application.id&&report.application_revision===application.revision&&report.total>0&&report.passed===report.total&&report.cases.length===report.total&&report.cases.every(c=>c.passed)&&JSON.stringify(normalizedCases(report.cases))===JSON.stringify(normalizedCases(cases));
}
