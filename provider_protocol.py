"""External provider-protocol.v1 envelope for sealed context packets."""
from __future__ import annotations
import argparse, copy, json, re, sys
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable
import context_packet as cp

PROTOCOL_VERSION="provider-protocol.v1"
MAX_WIRE_BYTES=1_310_720
_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FIELDS={"protocol_version","envelope_id","provider_id","model_id","request_id","packet"}

class ProviderProtocolError(ValueError): pass
class ProviderProtocolParseError(ProviderProtocolError): pass
class ProviderProtocolValidationError(ProviderProtocolError): pass
class ProviderProtocolAdapterError(ProviderProtocolError): pass

@runtime_checkable
class ProviderAdapter(Protocol):
 def fetch_packet(self, *, provider_id:str, model_id:str, request_id:str, previous_packet:dict[str,object]|None, now:datetime)->dict[str,object]: ...

def _fail(message:str)->None: raise ProviderProtocolValidationError(message)
def _id(value:object,path:str)->None:
 if not isinstance(value,str) or not _ID.fullmatch(value): _fail(f"{path} is not a valid identifier")
def _aware(now:datetime)->None:
 if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None: _fail("now must be timezone-aware")

def validate_envelope(envelope:dict[str,object],*,now:datetime|None=None,require_fresh:bool=True)->None:
 if not isinstance(envelope,dict): _fail("envelope must be an object")
 missing=_FIELDS-set(envelope); extra=set(envelope)-_FIELDS
 if missing: _fail("missing fields: "+", ".join(sorted(missing)))
 if extra: _fail("unexpected fields: "+", ".join(sorted(extra)))
 if envelope["protocol_version"]!=PROTOCOL_VERSION: _fail(f"protocol_version must be {PROTOCOL_VERSION!r}")
 for key in ("envelope_id","provider_id","model_id","request_id"): _id(envelope[key],key)
 cp.validate_packet(envelope["packet"],now=now,require_fresh=require_fresh)

def make_envelope(*,envelope_id:str,provider_id:str,model_id:str,request_id:str,packet:dict[str,object],now:datetime|None=None)->dict[str,object]:
 result={"protocol_version":PROTOCOL_VERSION,"envelope_id":envelope_id,"provider_id":provider_id,"model_id":model_id,"request_id":request_id,"packet":copy.deepcopy(packet)}
 validate_envelope(result,now=now)
 return result

def _pairs(pairs:list[tuple[str,object]])->dict[str,object]:
 result={}
 for key,value in pairs:
  if key in result: raise ProviderProtocolParseError(f"duplicate JSON key: {key}")
  result[key]=value
 return result
def _reject_number(value:str)->object: raise ProviderProtocolParseError(f"floating-point JSON numbers are forbidden: {value}")

def loads_envelope(data:str|bytes,*,now:datetime|None=None,require_fresh:bool=True)->dict[str,object]:
 try:
  if isinstance(data,bytes): size=len(data); text=data.decode("utf-8")
  elif isinstance(data,str): size=len(data.encode("utf-8")); text=data
  else: raise TypeError("input must be str or bytes")
  if size>MAX_WIRE_BYTES: raise ProviderProtocolParseError(f"provider envelope exceeds {MAX_WIRE_BYTES} byte wire size limit")
  value=json.loads(text,object_pairs_hook=_pairs,parse_float=_reject_number,parse_constant=_reject_number)
 except ProviderProtocolError: raise
 except (UnicodeError,json.JSONDecodeError,TypeError,ValueError) as exc: raise ProviderProtocolParseError(f"invalid provider envelope JSON: {exc}") from exc
 if not isinstance(value,dict): raise ProviderProtocolParseError("provider envelope JSON must be an object")
 try: validate_envelope(value,now=now,require_fresh=require_fresh)
 except UnicodeError as exc: raise ProviderProtocolValidationError("invalid Unicode scalar value") from exc
 return value

def dumps_envelope(envelope:dict[str,object])->str:
 validate_envelope(envelope,require_fresh=False)
 return cp.canonical_json_bytes(envelope).decode("utf-8")

def refresh_envelope(envelope:dict[str,object],adapter:ProviderAdapter,*,now:datetime)->dict[str,object]:
 _aware(now); validate_envelope(envelope,now=now,require_fresh=False)
 try:
  packet=adapter.fetch_packet(provider_id=envelope["provider_id"],model_id=envelope["model_id"],request_id=envelope["request_id"],previous_packet=copy.deepcopy(envelope["packet"]),now=now)
 except Exception as exc: raise ProviderProtocolAdapterError("provider adapter failed") from exc
 try: cp.validate_packet(packet,now=now,require_fresh=True)
 except (cp.ContextPacketError,TypeError,AttributeError) as exc: raise ProviderProtocolAdapterError("provider adapter returned an invalid context packet") from exc
 result=copy.deepcopy(envelope); result["packet"]=copy.deepcopy(packet); validate_envelope(result,now=now); return result

def _parse_time(text:str)->datetime:
 try:
  if not text.endswith("Z"): raise ValueError
  value=datetime.fromisoformat(text[:-1]+"+00:00"); _aware(value); return value
 except ValueError as exc: raise argparse.ArgumentTypeError("now must be an RFC 3339 UTC timestamp") from exc

def main(argv:list[str]|None=None)->int:
 parser=argparse.ArgumentParser(description="Validate provider-protocol.v1 envelope")
 sub=parser.add_subparsers(dest="command",required=True); validate=sub.add_parser("validate")
 validate.add_argument("path"); validate.add_argument("--envelope-id",required=True); validate.add_argument("--provider-id",required=True); validate.add_argument("--model-id",required=True); validate.add_argument("--request-id",required=True); validate.add_argument("--now",type=_parse_time,required=True)
 args=parser.parse_args(argv)
 try:
  env=loads_envelope(open(args.path,"rb").read(),now=args.now)
  for key in ("envelope_id","provider_id","model_id","request_id"):
   if env[key]!=getattr(args,key): raise ProviderProtocolValidationError(f"{key} mismatch: expected {getattr(args,key)!r}")
 except (OSError,ProviderProtocolError,cp.ContextPacketError) as exc: print(f"provider envelope validation failed: {exc}",file=sys.stderr); return 1
 print("provider-protocol.v1 envelope valid")
 return 0
if __name__=="__main__": raise SystemExit(main())
