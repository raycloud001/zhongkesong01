from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, uuid
from typing import Any
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from app.assessment.models import AssessmentEvent, AssessmentSubmission
from app.auth.service import AuthError
from app.jobs.store import enqueue_job
from app.models import AssessmentAnswer, AssessmentSession, ContentVersion, ProfileSnapshot, VersionPointer

class DomainError(AuthError): pass
PUBLIC_FIELDS = {"id","type","text","required","options","fields","minSelections","maxSelections","min","max","maxLength"}

def _question_version(db: Session, requested: str | None = None, required_mode: str | None = None) -> ContentVersion:
    version = db.get(ContentVersion, requested) if requested else db.scalar(select(ContentVersion).join(VersionPointer, VersionPointer.version_id == ContentVersion.id).where(VersionPointer.kind == "question"))
    questions = version.payload.get("questions") if version and isinstance(version.payload, dict) else None
    if version is None or version.kind != "question" or version.status != "published" or not isinstance(questions, list) or len(questions) != 40 or (required_mode and version.payload.get("metadata",{}).get("mode") != required_mode):
        raise DomainError(422,"REFERENCE_INVALID","Question version is not compatible and published")
    return version

def public_questions(version):
    return [{k:v for k,v in q.items() if k in PUBLIC_FIELDS} for q in version.payload["questions"]]

def create_assessment(db, owner_id, question_version=None, required_mode=None):
    version = _question_version(db, question_version, required_mode)
    assessment = AssessmentSession(id=str(uuid.uuid4()), owner_id=owner_id, question_version_id=version.id)
    db.add(assessment); db.commit()
    return {"id":assessment.id,"revision":0,"status":"draft","questionVersion":version.id,"questions":public_questions(version),"answers":[],"progress":{"answeredCount":0,"totalCount":40},"jobId":None,"demo":version.payload.get("metadata",{}).get("mode")=="demo"}

def _owned_session(db, owner_id, session_id):
    assessment=db.scalar(select(AssessmentSession).where(AssessmentSession.id==session_id,AssessmentSession.owner_id==owner_id))
    if assessment is None: raise DomainError(404,"NOT_FOUND","Resource not found")
    return assessment

def _question(version, question_id):
    result=next((q for q in version.payload["questions"] if q["id"]==question_id),None)
    if result is None: raise DomainError(422,"REFERENCE_INVALID","Question does not belong to this version")
    return result

def _valid_value(q, value, final=False):
    if q["type"] == "compound":
        if not isinstance(value, dict): return False
        fields = {field["id"]: field for field in q.get("fields", [])}
        if set(value) - set(fields): return False
        for field_id, field in fields.items():
            condition = field.get("condition")
            active = not condition or value.get(condition["field"]) == condition["equals"]
            if not active:
                if field_id in value: return False
                continue
            field_value = value.get(field_id)
            required = field.get("required") or (field.get("requiredWhenCondition") and active)
            missing = field_value in (None, "", []) or (isinstance(field_value, str) and not field_value.strip())
            if final and required and missing: return False
            if field_value in (None, ""): continue
            if not _valid_field(field, field_value): return False
        combined_field = next((f for f in fields.values() if f.get("combinedLength")), None)
        combined = combined_field.get("combinedLength") if combined_field else None
        if combined and (not combined_field.get("condition") or value.get(combined_field["condition"]["field"]) == combined_field["condition"]["equals"]):
            text = "".join(str(value.get(name, "")) for name in combined["fields"])
            if len(text) > combined["max"] or (final and len(text) < combined["min"]): return False
        return True
    if q["type"]=="scale": return isinstance(value,(int,float)) and not isinstance(value,bool) and q["min"]<=value<=q["max"]
    if q["type"]=="single": return isinstance(value,str) and value in {o["id"] for o in q["options"]}
    if q["type"]=="multiple":
        field=(q.get("fields") or [{}])[0]; choices={o["id"] for o in q["options"]}
        minimum=field.get("minSelections",q.get("minSelections",1)) if final else 0
        return isinstance(value,list) and len(value)==len(set(value)) and minimum<=len(value)<=field.get("maxSelections",q.get("maxSelections",len(choices))) and all(x in choices for x in value)
    return q["type"]=="experience" and isinstance(value,str) and len(value)<=q["maxLength"] and (not final or bool(value.strip()))

def _valid_field(field, value):
    kind = field["type"]
    if kind == "single": return isinstance(value, str) and value in {o["id"] for o in field.get("options", [])}
    if kind == "multiple": return isinstance(value, list) and len(value) == len(set(value)) and field.get("minSelections", 1) <= len(value) <= field.get("maxSelections", len(field.get("options", []))) and all(x in {o["id"] for o in field.get("options", [])} for x in value)
    if kind == "integer": return isinstance(value, int) and not isinstance(value, bool) and field.get("min", value) <= value <= field.get("max", value)
    if kind == "text": return isinstance(value, str) and len(value) <= field.get("maxLength", 10_000)
    if kind == "audio" and field.get("status") == "pending_implementation": return False
    return kind == "audio" and isinstance(value, str)

def save_answer(db, owner_id, session_id, question_id, value, revision):
    assessment=_owned_session(db,owner_id,session_id); version=_question_version(db,assessment.question_version_id)
    if not _valid_value(_question(version,question_id),value,final=False): raise DomainError(422,"INPUT_INVALID","Answer is invalid")
    changed=db.execute(update(AssessmentSession).where(AssessmentSession.id==session_id,AssessmentSession.owner_id==owner_id,AssessmentSession.status=="draft",AssessmentSession.revision==revision).values(revision=revision+1).execution_options(synchronize_session=False))
    if changed.rowcount!=1:
        db.rollback(); current=_owned_session(db,owner_id,session_id)
        raise DomainError(409,"ALREADY_SUBMITTED" if current.status!="draft" else "REVISION_CONFLICT","Assessment draft cannot be changed")
    answer=db.scalar(select(AssessmentAnswer).where(AssessmentAnswer.session_id==session_id,AssessmentAnswer.question_id==question_id))
    if answer is None: db.add(AssessmentAnswer(id=str(uuid.uuid4()),session_id=session_id,question_id=question_id,value={"value":value}))
    else: answer.value,answer.revision={"value":value},answer.revision+1
    db.commit(); count=db.scalar(select(func.count()).select_from(AssessmentAnswer).where(AssessmentAnswer.session_id==session_id)) or 0
    return revision+1,count

def session_detail(db,owner_id,session_id):
    a=_owned_session(db,owner_id,session_id); version=_question_version(db,a.question_version_id)
    answers=db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.session_id==session_id).order_by(AssessmentAnswer.question_id)).all()
    submission=db.scalar(select(AssessmentSubmission).where(AssessmentSubmission.owner_id==owner_id,AssessmentSubmission.session_id==session_id))
    return {"id":a.id,"status":a.status,"revision":a.revision,"questionVersion":a.question_version_id,"answers":[{"questionId":x.question_id,"value":x.value["value"]} for x in answers],"progress":{"answeredCount":len(answers),"totalCount":40},"questions":public_questions(version),"jobId":submission.job_id if submission else None,"demo":version.payload.get("metadata",{}).get("mode")=="demo"}

def current_session(db,owner_id,required_mode=None):
    query=select(AssessmentSession).where(AssessmentSession.owner_id==owner_id).order_by(AssessmentSession.created_at.desc())
    candidates=db.scalars(query).all()
    a=next((item for item in candidates if not required_mode or _question_version(db,item.question_version_id).payload.get("metadata",{}).get("mode")==required_mode),None)
    return session_detail(db,owner_id,a.id) if a else None

def _version_payload(db,kind,bundle,marker):
    version=db.scalar(select(ContentVersion).join(VersionPointer,VersionPointer.version_id==ContentVersion.id).where(VersionPointer.kind==kind,ContentVersion.status=="published"))
    if version: return version.id,version.payload
    demo=bundle.payload.get("metadata",{}).get("mode")=="demo"
    if demo and kind in {"rule","job_template"}: return bundle.id,bundle.payload["rules" if kind=="rule" else "jobTemplates"]
    if demo: return marker,{"demo":True,"available":False}
    if bundle.payload.get("metadata",{}).get("mode") == "evidence_only" and kind in {"job_template","prompt","knowledge_index"}: return marker,{"mode":"evidence_only","available":False}
    raise DomainError(503,"PROVIDER_UNAVAILABLE",f"Published {kind} version is unavailable")

def submit_assessment(db,owner_id,session_id,key):
    if not key or len(key)>200: raise DomainError(422,"INPUT_INVALID","Idempotency-Key is required")
    existing=db.scalar(select(AssessmentSubmission).where(AssessmentSubmission.owner_id==owner_id,AssessmentSubmission.session_id==session_id,AssessmentSubmission.idempotency_key==key))
    if existing: return existing.job_id
    a=_owned_session(db,owner_id,session_id); bundle=_question_version(db,a.question_version_id)
    answers=db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.session_id==session_id)).all(); by_id={x.question_id:x.value["value"] for x in answers}; questions=bundle.payload["questions"]
    if any((q.get("required", False) and q["id"] not in by_id) or (q["id"] in by_id and not _valid_value(q,by_id[q["id"]],final=True)) for q in questions):
        raise DomainError(422,"INPUT_INVALID","All required answers are required")
    mode=bundle.payload.get("metadata",{}).get("mode")
    markers={
        "rule":"demo-unavailable-rule" if mode=="demo" else "evidence-unavailable-rule",
        "job_template":"demo-unavailable-jobs" if mode=="demo" else "evidence-unavailable-job-template",
        "prompt":"demo-unavailable-prompt" if mode=="demo" else "evidence-unavailable-prompt",
        "knowledge_index":"demo-unavailable-knowledge-index" if mode=="demo" else "evidence-unavailable-knowledge-index",
    }
    rule_id,rules=_version_payload(db,"rule",bundle,markers["rule"]); jobs_id,jobs=_version_payload(db,"job_template",bundle,markers["job_template"]); prompt_id,prompt=_version_payload(db,"prompt",bundle,markers["prompt"]); index_id,index=_version_payload(db,"knowledge_index",bundle,markers["knowledge_index"])
    profile=db.scalar(select(ProfileSnapshot).where(ProfileSnapshot.owner_id==owner_id).order_by(ProfileSnapshot.created_at.desc()))
    model_marker="demo-unavailable-provider" if mode=="demo" else "evidence-unavailable-model"
    embedding_marker="demo-unavailable-embedding" if mode=="demo" else "evidence-unavailable-embedding"
    versions={"questionVersion":bundle.id,"ruleVersion":rule_id,"jobTemplateVersion":jobs_id,"knowledgeIndexVersion":index_id,"promptVersion":prompt_id,"modelName":os.getenv("MODELSCOPE_MODEL_NAME","").strip() or model_marker,"embeddingModelVersion":os.getenv("MODELSCOPE_EMBEDDING_MODEL","").strip() or embedding_marker,"profileSnapshotId":profile.id if profile else None}
    ordered=[{"questionId":q["id"],"value":by_id[q["id"]]} for q in questions if q["id"] in by_id]; canonical={"answers":ordered,"sourceVersions":versions}
    snapshot={"assessmentId":session_id,"inputHash":hashlib.sha256(json.dumps(canonical,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),"sourceVersions":versions,"answers":ordered,"contentBundle":json.loads(json.dumps(bundle.payload)),"sourcePayloads":{"rules":rules,"jobTemplates":jobs,"prompt":prompt,"knowledgeIndex":index},"profileSnapshotId":profile.id if profile else None}
    changed=db.execute(update(AssessmentSession).where(AssessmentSession.id==session_id,AssessmentSession.owner_id==owner_id,AssessmentSession.status=="draft",AssessmentSession.revision==a.revision).values(status="submitted",submitted_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
    if changed.rowcount!=1:
        db.rollback()
        existing=db.scalar(select(AssessmentSubmission).where(AssessmentSubmission.owner_id==owner_id,AssessmentSubmission.session_id==session_id,AssessmentSubmission.idempotency_key==key))
        if existing: return existing.job_id
        raise DomainError(409,"ALREADY_SUBMITTED","Assessment is already submitted")
    queued=enqueue_job(db,owner_id,snapshot); db.add(AssessmentSubmission(id=str(uuid.uuid4()),owner_id=owner_id,session_id=session_id,idempotency_key=key,job_id=queued)); db.commit(); return queued

ALLOWED_EVENTS={"assessment_start","question_view","question_answer","question_back","assessment_save","assessment_exit","assessment_submit"}
def record_event(db,owner_id,session_id,client_event_id,event_type,metadata):
    _owned_session(db,owner_id,session_id)
    if event_type not in ALLOWED_EVENTS or any(key not in {"questionId","status"} for key in metadata):
        raise DomainError(422,"INPUT_INVALID","Assessment event is invalid")
    existing=db.scalar(select(AssessmentEvent).where(AssessmentEvent.owner_id==owner_id,AssessmentEvent.client_event_id==client_event_id))
    if existing: return
    db.add(AssessmentEvent(id=str(uuid.uuid4()),owner_id=owner_id,session_id=session_id,client_event_id=client_event_id,event_type=event_type,metadata_json=metadata)); db.commit()
