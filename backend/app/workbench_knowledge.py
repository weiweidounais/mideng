from .pilot_service import business_roles
"""Read-only, project-authorized question routing and published-text lookup."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from .knowledge_models import Library, KnowledgeDocument


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1000)


class Source(BaseModel):
    library_id: str
    library_name: str
    document_id: str
    name: str
    location: str
    content: str
    truncated: bool


class Entry(BaseModel):
    section: Literal['requirements', 'procurement', 'changes', 'trace', 'cost', 'assurance', 'knowledge']
    title: str
    reason: str


class Answer(BaseModel):
    project_id: str
    query: str
    mode: Literal['keyword'] = 'keyword'
    model_enabled: Literal[False] = False
    keywords: list[str]
    sources: list[Source]
    entries: list[Entry]
    notice: str


# These classify the question, not the status of any business object.
INTENTS = (
    ('requirements', '需求与方案', ('需求', '方案', '设计', '图纸', 'BOM', '市场')),
    ('procurement', '交接与采购', ('采购', '下单', '订购', '合同', '材料', '到货', '交接', '归档', '商务')),
    ('trace', '管段与质量', ('质量', '验收', '到货', '管段', '检测', '工厂', '生产', '现场', '施工', '扫码', '拍照')),
    ('changes', '变更与处置', ('变更', '处置', '整改', '返修')),
    ('cost', '成本与月结', ('成本', '财务', '月结', '结算')),
    ('assurance', '异常与证据', ('异常', '证据', '审计', '导出')),
    ('knowledge', '项目知识与应用', ('知识', '资料', '导入', '上传', '应用', '规则', '模板', '模版')),
)


def keywords(query):
    lowered = query.casefold()
    terms = [word for _, _, words in INTENTS for word in words if word.casefold() in lowered]
    # Keep arbitrary names/codes usable without adding a model or tokenizer.
    clauses = re.split(r'[\s，。！？、,;；?！!：:]+', query)
    for clause in clauses:
        cleaned = re.sub(r'^(请问|请帮我|帮我|我想问|我想|如何|怎么)', '', clause)
        cleaned = re.sub(r'(应该怎么办|怎么处理|如何处理|怎么办|怎么做|怎么|如何|是什么|在哪里|在哪|吗|呢)$', '', cleaned)
        if len(cleaned) >= 2:
            terms.append(cleaned[:100])
    return list(dict.fromkeys(terms))[:24]


def answer_question(store, db, actor, pid, question):
    _, membership = store.membership(db, actor, pid)
    terms = keywords(question.query)
    entries = []
    for section, title, words in INTENTS:
        matched = [word for word in words if word.casefold() in question.query.casefold()]
        if not matched or (section == 'cost' and not set(business_roles(membership.roles)) & {'财务', '项目经理'}):
            continue
        if section == 'cost' and '财务' not in business_roles(membership.roles):
            title = '已发布成本汇总'
        entries.append(Entry(section=section, title=title, reason='问题包含：' + '、'.join(matched)))

    libraries = select(Library).where(Library.project_id == pid)
    # Evaluate the same exact space ACL before reading any document chunks.
    candidates = []
    for library in db.scalars(libraries.order_by(Library.id)):
        if library.restricted and actor.id != library.owner_id and actor.id not in library.readers:
            continue
        documents = select(KnowledgeDocument).where(
            KnowledgeDocument.project_id == pid, KnowledgeDocument.library_id == library.id,
            KnowledgeDocument.state == 'published').order_by(KnowledgeDocument.id)
        for document in db.scalars(documents):
            for index, chunk in enumerate(document.chunks):
                content = chunk['content']
                matches = [term for term in terms if term.casefold() in content.casefold()]
                if not matches:
                    continue
                first = min(content.casefold().find(term.casefold()) for term in matches)
                start = max(0, first - 180)
                excerpt = content[start:start + 1000]
                candidates.append((len(matches), library.id, document.id, index, Source(
                    library_id=library.id, library_name=library.name, document_id=document.id,
                    name=document.name, location=chunk['location'], content=excerpt,
                    truncated=start > 0 or len(content) > start + len(excerpt))))
    candidates.sort(key=lambda item: (-item[0], *item[1:4]))
    sources = [item[4] for item in candidates[:6]]
    notice = ('找到以下已发布资料原文，请核对后再进入业务。' if sources else
              '当前可读的已发布资料中未找到相关原文；可换用资料中的关键词，或进入知识空间导入并发布资料。')
    return Answer(project_id=pid, query=question.query, keywords=terms, sources=sources, entries=entries,
                  notice=notice + ' 业务入口按问题关键词匹配，不代表当前流程状态；未启用AI生成。')
